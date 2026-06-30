"""In-memory assignment queue for Soft Yeti coordinator tasks."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from typing import Any

from coordinator.canary import choose_canary, should_inject
from coordinator.config import Settings, get_settings
from coordinator.schemas import TaskAssignment, TaskRequest


class TaskQueue:
    """Queue sanitized prompts and track assigned work until completion."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[TaskAssignment] = asyncio.Queue()
        self._pending: dict[str, TaskAssignment] = {}
        self._lock = asyncio.Lock()
        self._result_events: dict[str, asyncio.Event] = {}
        self._result_store: dict[str, str] = {}

    @property
    def pending(self) -> dict[str, TaskAssignment]:
        """Return a shallow copy of pending assignments keyed by assignment id."""

        return dict(self._pending)

    def _assignment_id(self, task_id: str, task_salt: str) -> str:
        """Create a stable salted assignment id from the client task id."""

        digest = hashlib.sha256(f"{task_id}:{task_salt}".encode("utf-8")).hexdigest()
        return f"{task_id}:{digest[:24]}"

    def _setting_value(self, settings: Any, name: str, default: Any) -> Any:
        return getattr(settings, name, default)

    def _build_assignment(
        self,
        task: TaskRequest,
        settings: Settings,
        inject_canary: bool,
    ) -> TaskAssignment:
        task_salt = secrets.token_hex(16)
        assignment_id = self._assignment_id(task.task_id, task_salt)
        difficulty_target = str(self._setting_value(settings, "DIFFICULTY_TARGET", "0000"))
        system = getattr(task, "system", "")
        temperature = float(getattr(task, "temperature", 0.3))

        if inject_canary:
            canary_rate = float(self._setting_value(settings, "CANARY_RATE", 0.0))
            if should_inject(canary_rate, f"{assignment_id}:{task_salt}"):
                canary = choose_canary(f"{assignment_id}:{task_salt}")
                return TaskAssignment(
                    task_id=assignment_id,
                    task_type=task.task_type,
                    system=system,
                    temperature=temperature,
                    prompt=canary.prompt,
                    max_tokens=task.max_tokens,
                    task_salt=task_salt,
                    difficulty_target=difficulty_target,
                    is_canary=True,
                    canary_task_id=canary.canary_id,
                )

        return TaskAssignment(
            task_id=assignment_id,
            task_type=task.task_type,
            system=system,
            temperature=temperature,
            prompt=task.prompt,
            max_tokens=task.max_tokens,
            task_salt=task_salt,
            difficulty_target=difficulty_target,
            is_canary=False,
            canary_task_id=None,
        )

    async def enqueue_prompt(
        self,
        task: TaskRequest,
        settings: Settings | None = None,
        inject_canary: bool = True,
    ) -> TaskAssignment:
        """Salt a task id, optionally replace it with a canary, and enqueue it."""

        assignment = self._build_assignment(task, settings or get_settings(), inject_canary)
        await self._queue.put(assignment)
        return assignment

    async def assign_next(self) -> TaskAssignment | None:
        """Assign the next queued task and track it as pending by assignment id."""

        try:
            assignment = self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

        async with self._lock:
            self._pending[assignment.task_id] = assignment
        return assignment

    async def complete_assignment(self, assignment_id: str) -> TaskAssignment | None:
        """Mark an assignment complete and remove it from pending work."""

        async with self._lock:
            return self._pending.pop(assignment_id, None)

    async def enqueue(self, assignment: TaskAssignment) -> None:
        """Enqueue a pre-built assignment."""

        await self._queue.put(assignment)

    async def dequeue(self) -> TaskAssignment:
        """Wait for the next assignment without marking it pending."""

        return await self._queue.get()

    async def register_waiter(self, assignment_id: str) -> asyncio.Event:
        """Register an asyncio.Event that fires when the assignment result is delivered."""

        ev = asyncio.Event()
        async with self._lock:
            self._result_events[assignment_id] = ev
        return ev

    async def deliver_result(self, assignment_id: str, output_text: str) -> None:
        """Store the volunteer's output and signal any registered waiter."""

        ev: asyncio.Event | None
        async with self._lock:
            self._result_store[assignment_id] = output_text
            ev = self._result_events.get(assignment_id)
        if ev is not None:
            ev.set()

    async def take_result(self, assignment_id: str) -> str | None:
        """Consume and return the stored result, or None if not present."""

        async with self._lock:
            self._result_events.pop(assignment_id, None)
            return self._result_store.pop(assignment_id, None)
