"""Submission verification for proof-of-inference mining."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from chain.wallet import verify_signature
from coordinator.auth import get_volunteer_security_info
from coordinator.canary import CANARY_TASKS, verify_canary_output
from coordinator.config import Settings
from coordinator.schemas import InferenceSubmission, TaskAssignment


MIN_OUTPUT_LENGTH = 10

# 900s task timeout / ~2s minimum inference = ~450 max plausible attempts.
# Any submission claiming more is either lying or running on hardware that
# doesn't exist — reject it rather than silently capping the reward.
MAX_NONCE_ATTEMPTS = 500


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _find_canary(canary_task_id: str):
    for canary in CANARY_TASKS:
        if canary.canary_id == canary_task_id:
            return canary
    return None


def _submission_signing_message(submission: InferenceSubmission) -> bytes:
    """Canonical bytes the volunteer signs to prove wallet ownership."""
    return json.dumps(
        {
            "miner_wallet": submission.miner_wallet,
            "nonce_attempts": submission.nonce_attempts,
            "output_hash": submission.output_hash,
            "task_id": submission.task_id,
            "task_salt": submission.task_salt,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


async def verify_submission(
    submission: InferenceSubmission,
    assignment: TaskAssignment,
    settings: Settings,
) -> tuple[bool, str]:
    """Validate a miner submission against its assignment and runtime settings."""

    # ── 0. nonce_attempts sanity bound ───────────────────────────────────────
    if submission.nonce_attempts > MAX_NONCE_ATTEMPTS:
        return False, f"nonce_attempts {submission.nonce_attempts} exceeds maximum {MAX_NONCE_ATTEMPTS}"

    # ── 1. PoI hash integrity ─────────────────────────────────────────────────
    expected_hash = hashlib.sha256(
        f"{submission.output_text}{submission.task_id}{submission.task_salt}".encode("utf-8")
    ).hexdigest()
    if expected_hash != submission.output_hash:
        return False, "hash mismatch"

    # ── 2. Difficulty target ──────────────────────────────────────────────────
    difficulty_target = str(
        _value(assignment, "difficulty_target", getattr(settings, "DIFFICULTY_TARGET", ""))
    )
    if difficulty_target and not submission.output_hash.startswith(difficulty_target):
        return False, "difficulty not met"

    # ── 3. Benchmark signature present ────────────────────────────────────────
    if not submission.benchmark_signature:
        return False, "missing benchmark"

    # ── 4. Wallet ownership: verify Ed25519 submission signature ──────────────
    vol_info = await get_volunteer_security_info(settings.DB_PATH, submission.volunteer_id)
    if vol_info is None:
        return False, "volunteer not found"

    stored_pubkey, stored_model = vol_info

    if not stored_pubkey:
        return False, "volunteer has no registered public key"

    signing_msg = _submission_signing_message(submission)
    try:
        sig_valid = verify_signature(stored_pubkey, signing_msg, submission.miner_signature)
    except Exception:
        sig_valid = False
    if not sig_valid:
        return False, "invalid wallet signature"

    # Verify the claimed pubkey matches what's stored
    if submission.miner_pubkey != stored_pubkey:
        return False, "pubkey mismatch"

    # ── 5. Model name cross-check ─────────────────────────────────────────────
    if stored_model and submission.model_name and submission.model_name != stored_model:
        return False, "model mismatch"

    # ── 6. Canary or minimum output length ────────────────────────────────────
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
