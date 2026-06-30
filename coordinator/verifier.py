"""Submission verification for proof-of-inference mining."""

from __future__ import annotations

import hashlib
from typing import Any

from coordinator.canary import CANARY_TASKS, verify_canary_output
from coordinator.config import Settings
from coordinator.schemas import InferenceSubmission, TaskAssignment


MIN_OUTPUT_LENGTH = 10


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _find_canary(canary_task_id: str):
    for canary in CANARY_TASKS:
        if canary.canary_id == canary_task_id:
            return canary
    return None


async def verify_submission(
    submission: InferenceSubmission,
    assignment: TaskAssignment,
    settings: Settings,
) -> tuple[bool, str]:
    """Validate a miner submission against its assignment and runtime settings."""

    expected_hash = hashlib.sha256(
        f"{submission.output_text}{submission.task_id}{submission.task_salt}".encode("utf-8")
    ).hexdigest()
    if expected_hash != submission.output_hash:
        return False, "hash mismatch"

    difficulty_target = str(
        _value(assignment, "difficulty_target", getattr(settings, "DIFFICULTY_TARGET", ""))
    )
    if difficulty_target and not submission.output_hash.startswith(difficulty_target):
        return False, "difficulty not met"

    if not submission.benchmark_signature:
        return False, "missing benchmark"

    is_canary = bool(_value(assignment, "is_canary", False))
    canary_task_id = _value(assignment, "canary_task_id")
    if is_canary:
        if not canary_task_id:
            return False, "missing canary id"
        canary = _find_canary(str(canary_task_id))
        if canary is None:
            return False, "unknown canary"
        if not verify_canary_output(canary, submission.output_text):
            return False, "canary mismatch"
    elif len(submission.output_text) < MIN_OUTPUT_LENGTH:
        return False, "output too short"

    return True, "ok"
