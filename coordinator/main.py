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
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from coordinator.auth import get_current_volunteer, register_volunteer
from coordinator.config import Settings, get_settings
from coordinator.database import init_db
from coordinator.minter import mint_block
from coordinator.registry import VolunteerRegistry
from coordinator.sanitizer import sanitize_output, sanitize_prompt
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

limiter = Limiter(key_func=get_remote_address)
_chain_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize coordinator storage before serving requests."""

    await init_db(settings.DB_PATH)
    yield


app = FastAPI(title="Soft Yeti Coordinator", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def _read_chain_jsonl() -> list[dict[str, Any]]:
    """Read all blocks from the JSONL chain store. Returns [] if file absent."""
    chain_path = Path(settings.CHAIN_STORE_PATH)
    if not chain_path.exists():
        return []
    blocks = []
    with chain_path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                blocks.append(json.loads(stripped))
    return blocks


def _last_chain_state() -> tuple[str, int]:
    """Return the previous block hash and next block index from the JSONL chain store."""
    blocks = _read_chain_jsonl()
    if not blocks:
        return "0" * 64, 0
    last_block = blocks[-1]
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
        await task_queue.take_result(assignment.task_id)  # clean up registered event
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
@limiter.limit("5/minute")
async def register(request: Request, registration: VolunteerRegistration) -> dict[str, str]:
    """Register a volunteer and return its one-time API key."""

    try:
        api_key = await register_volunteer(settings.DB_PATH, registration)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
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
@limiter.limit("30/minute")
async def submit_inference(
    request: Request,
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

    async with _chain_lock:
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
    await task_queue.deliver_result(submission.task_id, sanitize_output(submission.output_text))

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
async def subscription_notify(
    transfer: TransferNotification,
    _: None = Depends(_require_jclaw_auth),
) -> dict[str, bool]:
    """Record a YETI transfer and extend the recipient subscription."""

    await record_transfer(settings.DB_PATH, transfer)
    return {"ok": True}


@app.get("/api/subscription/check/{wallet}")
async def subscription_check(wallet: str) -> dict[str, bool]:
    """Return whether a wallet currently has an active subscription."""

    return {"subscribed": await is_subscribed(settings.DB_PATH, wallet)}


# ---------------------------------------------------------------------------
# Chain read routes — read directly from the JSONL store (no ChainStorage/
# ChainManager needed; the SQLite-indexed chain node is a Phase 2 upgrade).
# ---------------------------------------------------------------------------

@app.get("/chain/height")
async def chain_height() -> dict[str, int]:
    return {"height": len(_read_chain_jsonl())}


@app.get("/chain/latest")
async def chain_latest() -> dict[str, Any]:
    blocks = _read_chain_jsonl()
    if not blocks:
        raise HTTPException(status_code=404, detail="Chain is empty")
    return blocks[-1]


@app.get("/chain/block/{index}")
async def chain_block(index: int) -> dict[str, Any]:
    blocks = _read_chain_jsonl()
    if index < 0 or index >= len(blocks):
        raise HTTPException(status_code=404, detail=f"Block {index} not found")
    return blocks[index]


@app.get("/chain/balance/{addr}")
async def chain_balance(addr: str) -> dict[str, Any]:
    blocks = _read_chain_jsonl()
    balance = sum(b.get("miner_reward", 0.0) for b in blocks if b.get("miner_wallet") == addr)
    return {"wallet": addr, "balance_yeti": round(balance, 8)}


@app.get("/chain/history/{addr}")
async def chain_history(addr: str) -> dict[str, Any]:
    blocks = _read_chain_jsonl()
    mined = [b for b in blocks if b.get("miner_wallet") == addr]
    return {"wallet": addr, "blocks": mined}


if __name__ == "__main__":
    uvicorn.run("coordinator.main:app", host="0.0.0.0", port=8000, reload=True)
