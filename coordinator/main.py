"""FastAPI entry point for the Soft Yeti coordinator backend."""

from __future__ import annotations

import asyncio
import json
import secrets as _secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status

from coordinator.auth import get_current_volunteer, register_volunteer
from coordinator.config import Settings, get_settings
from coordinator.database import init_db
from coordinator.minter import mint_block
from coordinator.registry import VolunteerRegistry
from coordinator.sanitizer import sanitize_prompt
from coordinator.schemas import (
    GenerateRequest,
    GenerateResponse,
    InferenceSubmission,
    SubmitResponse,
    TaskAssignment,
    TaskRequest,
    TransferNotification,
    VolunteerRegistration,
)
from coordinator.subscription import is_subscribed, record_transfer
from coordinator.task_queue import TaskQueue
from coordinator.verifier import verify_submission

settings = get_settings()
registry = VolunteerRegistry()
task_queue = TaskQueue()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize coordinator storage before serving requests."""

    await init_db(settings.DB_PATH)
    yield


app = FastAPI(title="Soft Yeti Coordinator", lifespan=lifespan)


def _last_chain_state() -> tuple[str, int]:
    """Return the previous block hash and next block index from the JSONL chain store."""

    chain_path = Path(settings.CHAIN_STORE_PATH)
    if not chain_path.exists():
        return "0" * 64, 0

    last_block: dict[str, Any] | None = None
    with chain_path.open("r", encoding="utf-8") as chain_file:
        for line in chain_file:
            stripped = line.strip()
            if stripped:
                last_block = json.loads(stripped)

    if last_block is None:
        return "0" * 64, 0

    prev_hash = str(last_block.get("block_hash", "0" * 64))
    next_index = int(last_block.get("index", -1)) + 1
    return prev_hash, next_index


def _append_block(block: dict[str, Any]) -> None:
    """Append a minted block to the local JSONL chain store."""

    chain_path = Path(settings.CHAIN_STORE_PATH)
    chain_path.parent.mkdir(parents=True, exist_ok=True)
    with chain_path.open("a", encoding="utf-8") as chain_file:
        chain_file.write(json.dumps(block, sort_keys=True, separators=(",", ":")) + "\n")


async def _require_jclaw_auth(request: Request) -> None:
    """FastAPI dependency for J-Claw → coordinator API calls.
    When JCLAW_API_KEY is unset the endpoint is open (Phase 0 testbed only).
    """
    if not settings.JCLAW_API_KEY:
        return
    provided = request.headers.get("X-JClaw-API-Key", "")
    if not _secrets.compare_digest(provided, settings.JCLAW_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid J-Claw API key")


@app.get("/api/health")
async def health() -> dict[str, int | str]:
    """Return coordinator health and live volunteer count."""

    return {
        "status": "ok",
        "healthy_volunteers": len(registry.healthy_volunteers()),
    }


@app.post("/api/generate", response_model=GenerateResponse)
async def generate(
    req: GenerateRequest,
    _: None = Depends(_require_jclaw_auth),
) -> GenerateResponse:
    """Blocking endpoint for J-Claw to submit a task and receive the volunteer's output.

    Enqueues the task, waits for a volunteer to complete it, then returns the output text.
    Returns 503 immediately when no healthy volunteers are registered, or on timeout.
    """
    if not registry.healthy_volunteers():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no volunteers available",
        )

    sanitized = await sanitize_prompt(req.prompt, req.task_type, settings)
    task = TaskRequest(
        task_id=req.task_id,
        task_type=req.task_type,
        prompt=sanitized,
        max_tokens=req.max_tokens,
    )
    # Carry system + temperature through to the volunteer via the assignment
    task_with_extras = type("_TaskWithExtras", (), {
        "task_id": req.task_id,
        "task_type": req.task_type,
        "prompt": sanitized,
        "max_tokens": req.max_tokens,
        "system": req.system,
        "temperature": req.temperature,
    })()

    assignment = await task_queue.enqueue_prompt(task_with_extras, settings=settings)
    ev = await task_queue.register_waiter(assignment.task_id)

    try:
        await asyncio.wait_for(ev.wait(), timeout=settings.GENERATE_TIMEOUT_S)
    except asyncio.TimeoutError:
        await task_queue.complete_assignment(assignment.task_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service unavailable: no volunteer completed the task in time",
        )

    output = await task_queue.take_result(assignment.task_id)
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service unavailable: result missing after delivery signal",
        )
    return GenerateResponse(task_id=req.task_id, output=output)


@app.get("/api/task/next", response_model=TaskAssignment)
async def get_next_task(
    volunteer_id: str = Depends(get_current_volunteer),
) -> TaskAssignment:
    """Volunteer polls for the next queued task without submitting a new one."""

    await registry.heartbeat(volunteer_id)
    assignment = await task_queue.assign_next()
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No task available")
    return assignment


@app.post("/api/register")
async def register(registration: VolunteerRegistration) -> dict[str, str]:
    """Register a volunteer and return its one-time API key."""

    api_key = await register_volunteer(settings.DB_PATH, registration)
    await registry.register_seen(
        volunteer_id=registration.volunteer_id,
        model_name=registration.model_name,
        vram_gb=registration.vram_gb,
        miner_wallet=registration.miner_wallet,
    )
    return {"volunteer_id": registration.volunteer_id, "api_key": api_key}


@app.post("/api/task")
async def assign_task(
    task: TaskRequest,
    volunteer_id: str = Depends(get_current_volunteer),
):
    """Queue and assign a task to an authenticated volunteer."""

    await registry.heartbeat(volunteer_id)
    await task_queue.enqueue_prompt(task, settings=settings)
    assignment = await task_queue.assign_next()
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No task available",
        )
    return assignment


@app.post("/api/submit", response_model=SubmitResponse)
async def submit_inference(
    submission: InferenceSubmission,
    volunteer_id: str = Depends(get_current_volunteer),
) -> SubmitResponse:
    """Verify a volunteer submission and mint a YETI block when accepted."""

    if submission.volunteer_id != volunteer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Submission volunteer does not match API key",
        )

    assignment = task_queue.pending.get(submission.task_id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown task assignment",
        )

    accepted, reason = await verify_submission(submission, assignment, settings)
    if not accepted:
        await registry.mark_failure(volunteer_id)
        return SubmitResponse(accepted=False, reason=reason)

    prev_hash, block_index = _last_chain_state()
    block = await mint_block(
        submission=submission,
        task_assignment=assignment,
        settings=settings,
        prev_hash=prev_hash,
        block_index=block_index,
    )
    _append_block(block)
    await task_queue.complete_assignment(submission.task_id)
    await task_queue.deliver_result(submission.task_id, submission.output_text)

    record = await registry.register_seen(
        volunteer_id=volunteer_id,
        miner_wallet=submission.miner_wallet,
    )
    record.tasks_completed += 1

    return SubmitResponse(
        accepted=True,
        reason="ok",
        block_index=block_index,
        miner_reward=float(block["miner_reward"]),
    )


@app.post("/api/heartbeat")
async def heartbeat(volunteer_id: str = Depends(get_current_volunteer)) -> dict[str, bool]:
    """Refresh the authenticated volunteer liveness timestamp."""

    ok = await registry.heartbeat(volunteer_id)
    if not ok:
        await registry.register_seen(volunteer_id=volunteer_id)
    return {"ok": True}


@app.post("/api/subscription/notify")
async def subscription_notify(transfer: TransferNotification) -> dict[str, bool]:
    """Record a YETI transfer and extend the recipient subscription."""

    await record_transfer(settings.DB_PATH, transfer)
    return {"ok": True}


@app.get("/api/subscription/check/{wallet}")
async def subscription_check(wallet: str) -> dict[str, bool]:
    """Return whether a wallet currently has an active subscription."""

    return {"subscribed": await is_subscribed(settings.DB_PATH, wallet)}


if __name__ == "__main__":
    uvicorn.run("coordinator.main:app", host="0.0.0.0", port=8000, reload=True)
