import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

from coordinator import main
from coordinator.database import init_db
from coordinator.registry import VolunteerRegistry
from coordinator.task_queue import TaskQueue


@pytest.fixture()
def anyio_backend():
    return "asyncio"


@pytest.fixture()
async def api_client(tmp_path, monkeypatch):
    db_path = tmp_path / "coordinator.db"
    chain_path = tmp_path / "yeti-chain.jsonl"

    monkeypatch.setattr(main.settings, "DB_PATH", str(db_path))
    monkeypatch.setattr(main.settings, "CHAIN_STORE_PATH", str(chain_path))
    monkeypatch.setattr(main.settings, "DIFFICULTY_TARGET", "")
    monkeypatch.setattr(main.settings, "JCLAW_API_KEY", "")
    monkeypatch.setattr(main, "registry", VolunteerRegistry())
    monkeypatch.setattr(main, "task_queue", TaskQueue())

    async def fake_verify_submission(submission, assignment, settings):
        return True, "ok"

    async def fake_mint_block(submission, task_assignment, settings, prev_hash, block_index):
        return {
            "version": 1,
            "chain_id": settings.CHAIN_ID,
            "index": block_index,
            "prev_hash": prev_hash,
            "task_id": submission.task_id,
            "task_salt": submission.task_salt,
            "output_hash": submission.output_hash,
            "difficulty_target": settings.DIFFICULTY_TARGET,
            "nonce_attempts": submission.nonce_attempts,
            "miner_wallet": submission.miner_wallet,
            "volunteer_id": submission.volunteer_id,
            "completion_tokens": submission.completion_tokens,
            "prompt_tokens": submission.prompt_tokens,
            "benchmark_signature": submission.benchmark_signature,
            "miner_reward": 0.01,
            "treasury_reward": 0.0,
            "coordinator_signature": "test-signature",
            "block_hash": "abc123",
        }

    monkeypatch.setattr(main, "verify_submission", fake_verify_submission)
    monkeypatch.setattr(main, "mint_block", fake_mint_block)

    await init_db(str(db_path))

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.anyio
async def test_health_register_auth_task_heartbeat_submit_and_subscription(api_client):
    health_response = await api_client.get("/api/health")
    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"
    assert health_response.json()["healthy_volunteers"] == 0

    registration = {
        "volunteer_id": "volunteer-1",
        "miner_wallet": "YETI1miner",
        "miner_pubkey": "aa" * 32,
        "model_name": "qwen2.5-coder:7b-instruct",
        "vram_gb": 12.0,
    }
    register_response = await api_client.post("/api/register", json=registration)
    assert register_response.status_code == 200
    register_payload = register_response.json()
    assert register_payload["volunteer_id"] == "volunteer-1"
    assert register_payload["api_key"]

    auth_headers = {
        main.settings.API_KEY_HEADER: f"volunteer-1:{register_payload['api_key']}"
    }

    unauthenticated_task_response = await api_client.post(
        "/api/task",
        json={
            "task_id": "task-unauthenticated",
            "task_type": "qa",
            "prompt": "This should require auth.",
            "max_tokens": 64,
        },
    )
    assert unauthenticated_task_response.status_code == 401

    task_request = {
        "task_id": "task-1",
        "task_type": "qa",
        "prompt": "Explain why deterministic API tests are useful.",
        "max_tokens": 64,
    }
    task_response = await api_client.post(
        "/api/task",
        json=task_request,
        headers=auth_headers,
    )
    assert task_response.status_code == 200
    assignment = task_response.json()
    assert assignment["task_id"].startswith("task-1:")
    assert assignment["task_type"] == "qa"
    assert assignment["prompt"] == task_request["prompt"]
    assert assignment["task_salt"]
    assert "difficulty_target" in assignment

    heartbeat_response = await api_client.post("/api/heartbeat", headers=auth_headers)
    assert heartbeat_response.status_code == 200
    assert heartbeat_response.json() == {"ok": True}

    output_text = "This accepted output is long enough for verifier checks."
    output_hash = hashlib.sha256(
        (output_text + assignment["task_id"] + assignment["task_salt"]).encode()
    ).hexdigest()
    submit_response = await api_client.post(
        "/api/submit",
        json={
            "task_id": assignment["task_id"],
            "volunteer_id": "volunteer-1",
            "miner_wallet": "YETI1miner",
            "miner_pubkey": "aa" * 32,
            "miner_signature": "bb" * 64,
            "model_name": "qwen2.5-coder:7b-instruct",
            "output_text": output_text,
            "output_hash": output_hash,
            "nonce_attempts": 7,
            "benchmark_signature": "benchmark-ok",
            "prompt_tokens": 8,
            "completion_tokens": 16,
            "task_salt": assignment["task_salt"],
        },
        headers=auth_headers,
    )
    assert submit_response.status_code == 200
    assert submit_response.json() == {
        "accepted": True,
        "reason": "ok",
        "block_index": 0,
        "miner_reward": 0.01,
    }

    notify_response = await api_client.post(
        "/api/subscription/notify",
        json={
            "from_wallet": "YETI1payer",
            "to_wallet": "YETI1subscriber",
            "amount": 1000.0,
            "block_index": 0,
        },
    )
    assert notify_response.status_code == 200
    assert notify_response.json() == {"ok": True}

    subscription_response = await api_client.get(
        "/api/subscription/check/YETI1subscriber"
    )
    assert subscription_response.status_code == 200
    assert subscription_response.json() == {"subscribed": True}

    final_health_response = await api_client.get("/api/health")
    assert final_health_response.status_code == 200
    assert final_health_response.json()["healthy_volunteers"] == 1
