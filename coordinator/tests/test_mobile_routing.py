"""Phase 3 verification gate: mobile (inference_backend != 'ollama') volunteers get
routed correctly and receive a backend-specific difficulty target, without breaking
existing desktop volunteer behavior. This is the fake-mobile-volunteer test called for
by the iPhone mobile-mining tier implementation plan — Track A is not done until this
passes end-to-end against the real FastAPI app (not mocked verification/minting).
"""

import hashlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from httpx import ASGITransport, AsyncClient

from coordinator import main
from coordinator.database import init_db
from coordinator.registry import VolunteerRegistry
from coordinator.task_queue import TaskQueue


@pytest.fixture()
def anyio_backend():
    return "asyncio"


def _keygen() -> tuple[str, str]:
    """Generate a test Ed25519 keypair. Returns (privkey_hex, pubkey_hex)."""
    privkey = Ed25519PrivateKey.generate()
    pubkey_hex = privkey.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    privkey_hex = privkey.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()
    return privkey_hex, pubkey_hex


def _sign(privkey_hex: str, miner_wallet: str, nonce_attempts: int, output_hash: str, task_id: str, task_salt: str) -> str:
    """Reproduce the exact canonical signing message the coordinator verifies against."""
    from chain.wallet import sign_message

    signing_msg = json.dumps(
        {
            "miner_wallet": miner_wallet,
            "nonce_attempts": nonce_attempts,
            "output_hash": output_hash,
            "task_id": task_id,
            "task_salt": task_salt,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sign_message(privkey_hex, signing_msg)


def _mine_output(task_id: str, task_salt: str, difficulty_target: str, base_text: str) -> tuple[str, str, int]:
    """Brute-force a real nonce meeting the given difficulty target (same as a real miner)."""
    for nonce in range(1, 200_000):
        output_text = f"{base_text} {nonce}"
        output_hash = hashlib.sha256(f"{output_text}{task_id}{task_salt}".encode("utf-8")).hexdigest()
        if output_hash.startswith(difficulty_target):
            return output_text, output_hash, nonce
    raise AssertionError(f"could not mine output for difficulty {difficulty_target!r}")


@pytest.fixture()
async def api_client(tmp_path, monkeypatch):
    """Real coordinator app, real verify_submission + mint_block (not mocked) — this
    test needs the actual protocol enforcement, not a stubbed-out happy path, since it's
    proving backend-aware difficulty routing actually works end-to-end.
    """
    db_path = tmp_path / "coordinator.db"
    chain_path = tmp_path / "yeti-chain.jsonl"
    key_path = tmp_path / "coordinator.key"

    private_key = Ed25519PrivateKey.generate()
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=Encoding.PEM, format=PrivateFormat.PKCS8, encryption_algorithm=NoEncryption()
        )
    )

    monkeypatch.setattr(main.settings, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.settings, "CHAIN_STORE_PATH", str(chain_path))
    monkeypatch.setattr(main.settings, "COORDINATOR_ED25519_KEY_PATH", str(key_path))
    monkeypatch.setattr(main.settings, "DIFFICULTY_TARGET", "0000")  # desktop: hard, near-impossible in test
    monkeypatch.setattr(main.settings, "DIFFICULTY_TARGET_METAL", "0")  # mobile: easy, matches most hashes
    monkeypatch.setattr(main.settings, "JCLAW_API_KEY", "")
    monkeypatch.setattr(main.settings, "CANARY_RATE", 0.0)  # no canary noise in this test

    real_registry = VolunteerRegistry()
    monkeypatch.setattr(main, "registry", real_registry)
    monkeypatch.setattr(main, "task_queue", TaskQueue(registry=real_registry))

    await init_db(str(db_path))

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.anyio
async def test_mobile_volunteer_gets_relaxed_difficulty_and_mints_tagged_block(api_client):
    """A metal/bitnet mobile volunteer registers, gets the mobile difficulty target,
    and successfully mines + submits a block carrying its backend/model_type tags."""

    privkey_hex, pubkey_hex = _keygen()
    registration = {
        "volunteer_id": "mobile-volunteer-1",
        "miner_wallet": "YETI1mobileminer",
        "miner_pubkey": pubkey_hex,
        "model_name": "bitnet-b1.58-2b-4t",
        "vram_gb": 0.0,
        "model_type": "bitnet",
        "inference_backend": "metal",
    }
    register_response = await api_client.post("/api/register", json=registration)
    assert register_response.status_code == 200
    api_key = register_response.json()["api_key"]
    auth_headers = {main.settings.API_KEY_HEADER: f"mobile-volunteer-1:{api_key}"}

    task_response = await api_client.post(
        "/api/task",
        json={
            "task_id": "mobile-task-1",
            "task_type": "qa",
            "prompt": "Describe a sunset in one sentence.",
            "max_tokens": 64,
        },
        headers=auth_headers,
    )
    assert task_response.status_code == 200
    assignment = task_response.json()

    # The core routing assertion: mobile backend got the relaxed target, not desktop's.
    assert assignment["difficulty_target"] == "0"

    output_text, output_hash, nonce_attempts = _mine_output(
        assignment["task_id"], assignment["task_salt"], assignment["difficulty_target"], "a golden sunset over the hills"
    )
    signature = _sign(privkey_hex, "YETI1mobileminer", nonce_attempts, output_hash, assignment["task_id"], assignment["task_salt"])

    submit_response = await api_client.post(
        "/api/submit",
        json={
            "task_id": assignment["task_id"],
            "volunteer_id": "mobile-volunteer-1",
            "miner_wallet": "YETI1mobileminer",
            "miner_pubkey": pubkey_hex,
            "miner_signature": signature,
            "model_name": "bitnet-b1.58-2b-4t",
            "output_text": output_text,
            "output_hash": output_hash,
            "nonce_attempts": nonce_attempts,
            "benchmark_signature": "benchmark-ok",
            "prompt_tokens": 8,
            "completion_tokens": 16,
            "task_salt": assignment["task_salt"],
            "model_type": "bitnet",
            "inference_backend": "metal",
        },
        headers=auth_headers,
    )
    assert submit_response.status_code == 200
    result = submit_response.json()
    assert result["accepted"] is True, result

    with open(main.settings.CHAIN_STORE_PATH, encoding="utf-8") as f:
        blocks = [json.loads(line) for line in f if line.strip()]
    assert len(blocks) == 1
    assert blocks[0]["inference_backend"] == "metal"
    assert blocks[0]["model_type"] == "bitnet"


@pytest.mark.anyio
async def test_desktop_volunteer_still_gets_default_difficulty_in_same_run(api_client):
    """Regression check: a plain desktop-style registration (no backend fields sent
    at all, matching an unmodified existing client) still gets the desktop difficulty
    target — proves the shared-queue routing change didn't break existing behavior."""

    registration = {
        "volunteer_id": "desktop-volunteer-1",
        "miner_wallet": "YETI1desktopminer",
        "miner_pubkey": "aa" * 32,
        "model_name": "qwen2.5-coder:7b-instruct",
        "vram_gb": 12.0,
        # note: no model_type / inference_backend keys at all — old-client shape
    }
    register_response = await api_client.post("/api/register", json=registration)
    assert register_response.status_code == 200
    api_key = register_response.json()["api_key"]
    auth_headers = {main.settings.API_KEY_HEADER: f"desktop-volunteer-1:{api_key}"}

    task_response = await api_client.post(
        "/api/task",
        json={
            "task_id": "desktop-task-1",
            "task_type": "qa",
            "prompt": "Explain recursion in one sentence.",
            "max_tokens": 64,
        },
        headers=auth_headers,
    )
    assert task_response.status_code == 200
    assignment = task_response.json()
    assert assignment["difficulty_target"] == "0000"
