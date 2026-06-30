"""YETI block minting and coordinator signing utilities."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import hashlib
import json
import time
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from coordinator.config import Settings
from coordinator.schemas import InferenceSubmission, TaskAssignment


async def load_coordinator_key(settings: Settings) -> Ed25519PrivateKey:
    """Load the coordinator Ed25519 private key from a PEM file."""

    key_path = Path(settings.COORDINATOR_ED25519_KEY_PATH)
    key_bytes = key_path.read_bytes()
    passphrase = settings.COORDINATOR_ED25519_KEY_PASS.get_secret_value()
    password = passphrase.encode() if passphrase else None
    private_key = load_pem_private_key(key_bytes, password=password)

    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("Coordinator key must be an Ed25519 private key")

    return private_key


def _canonical_json(payload: dict[str, Any]) -> bytes:
    """Return deterministic JSON bytes for signing and hashing."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


async def mint_block(
    submission: InferenceSubmission,
    task_assignment: TaskAssignment,
    settings: Settings,
    prev_hash: str,
    block_index: int,
) -> dict[str, Any]:
    """Mint a signed YETI proof-of-inference block dictionary."""

    gross = submission.completion_tokens * settings.REWARD_RATE * submission.nonce_attempts
    miner_reward = gross * (1.0 - settings.TREASURY_FEE)
    treasury_reward = gross * settings.TREASURY_FEE

    block: dict[str, Any] = {
        "version": 1,
        "chain_id": settings.CHAIN_ID,
        "index": block_index,
        "timestamp": time.time(),
        "prev_hash": prev_hash,
        "task_id": submission.task_id,
        "task_salt": submission.task_salt,
        "task_content_hash": hashlib.sha256(task_assignment.prompt.encode()).hexdigest(),
        "output_hash": submission.output_hash,
        "difficulty_target": task_assignment.difficulty_target,
        "nonce_attempts": submission.nonce_attempts,
        "miner_wallet": submission.miner_wallet,
        "volunteer_id": submission.volunteer_id,
        "completion_tokens": submission.completion_tokens,
        "prompt_tokens": submission.prompt_tokens,
        "benchmark_signature": submission.benchmark_signature,
        "zk_proof": "",
        "miner_reward": miner_reward,
        "treasury_reward": treasury_reward,
        "coordinator_signature": "",
    }

    signing_payload = dict(block)
    signing_payload.pop("coordinator_signature", None)
    signing_payload.pop("block_hash", None)

    private_key = await load_coordinator_key(settings)
    signature = private_key.sign(_canonical_json(signing_payload))
    signature_hex = signature.hex()

    block["coordinator_signature"] = signature_hex
    block["block_hash"] = hashlib.sha256(_canonical_json(block)).hexdigest()

    return block
