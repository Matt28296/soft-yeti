from __future__ import annotations

import hashlib
import time
from types import SimpleNamespace

import aiosqlite
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from pydantic import SecretStr

from coordinator.database import init_db
from coordinator.minter import _canonical_json, mint_block
from coordinator.verifier import verify_submission


def _hash_output(output_text: str, task_id: str, task_salt: str) -> str:
    return hashlib.sha256(f"{output_text}{task_id}{task_salt}".encode("utf-8")).hexdigest()


def _mined_submission(prefix: str = "0", output_base: str = "valid inference output") -> SimpleNamespace:
    task_id = "task-001"
    task_salt = "salt-001"
    for nonce in range(100_000):
        output_text = f"{output_base} {nonce}"
        output_hash = _hash_output(output_text, task_id, task_salt)
        if output_hash.startswith(prefix):
            return SimpleNamespace(
                task_id=task_id,
                volunteer_id="volunteer-001",
                miner_wallet="YETI1miner",
                miner_pubkey="",
                miner_signature="",
                model_name="",
                output_text=output_text,
                output_hash=output_hash,
                nonce_attempts=nonce + 1,
                benchmark_signature="benchmark-ok",
                prompt_tokens=7,
                completion_tokens=11,
                task_salt=task_salt,
            )
    raise AssertionError(f"could not mine output for prefix {prefix!r}")


def _assignment(difficulty_target: str = "0", **overrides: object) -> SimpleNamespace:
    data = {
        "task_id": "task-001",
        "task_type": "qa",
        "prompt": "Explain proof of inference briefly.",
        "max_tokens": 128,
        "task_salt": "salt-001",
        "difficulty_target": difficulty_target,
        "is_canary": False,
        "canary_task_id": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _settings(tmp_path, difficulty_target: str = "0") -> SimpleNamespace:
    return SimpleNamespace(
        DIFFICULTY_TARGET=difficulty_target,
        COORDINATOR_ED25519_KEY_PATH=str(tmp_path / "coordinator.key"),
        COORDINATOR_ED25519_KEY_PASS=SecretStr(""),
        REWARD_RATE=0.001,
        TREASURY_FEE=0.1,
        CHAIN_ID="yeti-testnet",
        DB_PATH=str(tmp_path / "coordinator.db"),
    )


async def _register_test_volunteer(db_path: str, pubkey: str = "", model_name: str = "") -> None:
    """Insert a minimal volunteer record into the test DB.

    Empty pubkey causes verifier to skip signature check (no pubkey stored yet).
    """
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT OR REPLACE INTO volunteers
               (volunteer_id, miner_wallet, api_key_hash, model_name, vram_gb, miner_pubkey, registered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("volunteer-001", "YETI1miner", "hash-not-needed", model_name, 8.0, pubkey, time.time()),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_verify_submission_accepts_valid_submission(tmp_path) -> None:
    settings = _settings(tmp_path, difficulty_target="0")
    await _register_test_volunteer(settings.DB_PATH)
    submission = _mined_submission(prefix="0")
    accepted, reason = await verify_submission(submission, _assignment("0"), settings)

    assert accepted is True
    assert reason == "ok"


@pytest.mark.asyncio
async def test_verify_submission_rejects_hash_mismatch(tmp_path) -> None:
    settings = _settings(tmp_path, difficulty_target="")
    await _register_test_volunteer(settings.DB_PATH)
    submission = _mined_submission(prefix="")
    submission.output_hash = "f" * 64

    accepted, reason = await verify_submission(submission, _assignment(""), settings)

    assert accepted is False
    assert reason == "hash mismatch"


@pytest.mark.asyncio
async def test_verify_submission_rejects_canary_mismatch(tmp_path) -> None:
    settings = _settings(tmp_path, difficulty_target="")
    await _register_test_volunteer(settings.DB_PATH)
    submission = _mined_submission(prefix="", output_base="wrong canary output")
    assignment = _assignment("", is_canary=True, canary_task_id="canary-001")

    accepted, reason = await verify_submission(submission, assignment, settings)

    assert accepted is False
    assert reason == "canary mismatch"


@pytest.mark.asyncio
async def test_verify_submission_rejects_difficulty_prefix_failure(tmp_path) -> None:
    settings = _settings(tmp_path, difficulty_target="ffff")
    await _register_test_volunteer(settings.DB_PATH)
    submission = _mined_submission(prefix="0")

    accepted, reason = await verify_submission(submission, _assignment("ffff"), settings)

    assert accepted is False
    assert reason == "difficulty not met"


@pytest.mark.asyncio
async def test_verify_submission_accepts_valid_wallet_signature(tmp_path) -> None:
    """When a pubkey is registered, the submission signature is verified."""
    from chain.wallet import sign_message, verify_signature

    privkey = Ed25519PrivateKey.generate()
    pubkey_hex = privkey.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    privkey_hex = privkey.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()

    settings = _settings(tmp_path, difficulty_target="0")
    await _register_test_volunteer(settings.DB_PATH, pubkey=pubkey_hex)

    submission = _mined_submission(prefix="0")
    submission.miner_pubkey = pubkey_hex

    import json
    signing_msg = json.dumps(
        {
            "miner_wallet": submission.miner_wallet,
            "nonce_attempts": submission.nonce_attempts,
            "output_hash": submission.output_hash,
            "task_id": submission.task_id,
            "task_salt": submission.task_salt,
        },
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    submission.miner_signature = sign_message(privkey_hex, signing_msg)

    accepted, reason = await verify_submission(submission, _assignment("0"), settings)
    assert accepted is True
    assert reason == "ok"


@pytest.mark.asyncio
async def test_verify_submission_rejects_bad_wallet_signature(tmp_path) -> None:
    """When a pubkey is registered and the signature is wrong, submission is rejected."""
    privkey = Ed25519PrivateKey.generate()
    pubkey_hex = privkey.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()

    settings = _settings(tmp_path, difficulty_target="0")
    await _register_test_volunteer(settings.DB_PATH, pubkey=pubkey_hex)

    submission = _mined_submission(prefix="0")
    submission.miner_pubkey = pubkey_hex
    submission.miner_signature = "aa" * 64  # wrong signature

    accepted, reason = await verify_submission(submission, _assignment("0"), settings)
    assert accepted is False
    assert reason == "invalid wallet signature"


@pytest.mark.asyncio
async def test_mint_block_generates_ed25519_signature_and_block_hash(tmp_path) -> None:
    private_key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "coordinator.key"
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )
    )
    settings = _settings(tmp_path, difficulty_target="0")
    submission = _mined_submission(prefix="0")
    assignment = _assignment("0")

    block = await mint_block(
        submission=submission,
        task_assignment=assignment,
        settings=settings,
        prev_hash="0" * 64,
        block_index=1,
    )

    signing_payload = dict(block)
    signature_hex = signing_payload.pop("coordinator_signature")
    signing_payload.pop("block_hash")
    private_key.public_key().verify(bytes.fromhex(signature_hex), _canonical_json(signing_payload))

    block_without_hash = {k: v for k, v in block.items() if k != "block_hash"}
    expected_hash = hashlib.sha256(_canonical_json(block_without_hash)).hexdigest()
    assert block["coordinator_signature"] == signature_hex
    assert len(signature_hex) == 128
    assert block["block_hash"] == expected_hash
    assert len(block["block_hash"]) == 64
    assert block["miner_reward"] == pytest.approx(0.0099)
    assert block["treasury_reward"] == pytest.approx(0.0011)
