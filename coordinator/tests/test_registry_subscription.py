import time

import aiosqlite
import pytest

from coordinator.database import init_db
from coordinator.registry import VolunteerRegistry
from coordinator.schemas import TransferNotification
from coordinator.subscription import (
    expire_old,
    get_expiry,
    get_subscription,
    is_active,
    record_transfer,
)


@pytest.mark.asyncio
async def test_registry_heartbeat_filters_only_recent_active_volunteers(monkeypatch):
    current_time = 1_700_000_000.0
    monkeypatch.setattr("coordinator.registry.utc_timestamp", lambda: current_time)

    registry = VolunteerRegistry(default_ttl=30.0)
    fresh = await registry.register_seen(
        "volunteer-fresh",
        model_name="qwen2.5-coder:7b-instruct",
        vram_gb=12.0,
        miner_wallet="YETI1fresh",
    )
    stale = await registry.register_seen(
        "volunteer-stale",
        model_name="qwen2.5-coder:7b-instruct",
        vram_gb=8.0,
        miner_wallet="YETI1stale",
    )
    inactive = await registry.register_seen(
        "volunteer-inactive",
        model_name="qwen2.5-coder:7b-instruct",
        vram_gb=16.0,
        miner_wallet="YETI1inactive",
    )

    current_time += 40.0
    assert await registry.heartbeat("volunteer-fresh") is True
    assert await registry.heartbeat("missing-volunteer") is False
    inactive.active = False

    healthy = registry.healthy_volunteers()

    assert [record.volunteer_id for record in healthy] == ["volunteer-fresh"]
    assert fresh.last_seen == current_time
    assert stale.last_seen == 1_700_000_000.0
    assert inactive.active is False


@pytest.mark.asyncio
async def test_record_transfer_extends_subscription_and_lookup_uses_temp_sqlite(tmp_path, monkeypatch):
    db_path = str(tmp_path / "subscriptions.db")
    await init_db(db_path)
    current_time = 1_700_000_000.0
    monkeypatch.setattr("coordinator.subscription.time.time", lambda: current_time)

    transfer = TransferNotification(
        from_wallet="YETI1payer",
        to_wallet="YETI1subscriber",
        amount=8_000.0,
        block_index=42,
    )

    await record_transfer(db_path, transfer)
    subscription = await get_subscription(db_path, "YETI1subscriber")
    first_expiry = await get_expiry(db_path, "YETI1subscriber")

    assert subscription == {
        "wallet_address": "YETI1subscriber",
        "subscribed": True,
        "expires_at": first_expiry,
    }
    assert first_expiry == pytest.approx(current_time + 90 * 86400)
    assert await is_active(db_path, "YETI1subscriber") is True
    assert await is_active(db_path, "YETI1missing") is False

    current_time += 10.0
    await record_transfer(db_path, transfer)
    second_expiry = await get_expiry(db_path, "YETI1subscriber")

    assert second_expiry == pytest.approx(first_expiry + 90 * 86400)


@pytest.mark.asyncio
async def test_subscription_expiry_status_and_cleanup_use_temp_sqlite(tmp_path, monkeypatch):
    db_path = str(tmp_path / "subscriptions.db")
    await init_db(db_path)
    current_time = 1_700_000_000.0
    monkeypatch.setattr("coordinator.subscription.time.time", lambda: current_time)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO subscriptions (wallet_address, expires_at) VALUES (?, ?)",
            ("YETI1expired", current_time - 1.0),
        )
        await db.execute(
            "INSERT INTO subscriptions (wallet_address, expires_at) VALUES (?, ?)",
            ("YETI1active", current_time + 60.0),
        )
        await db.commit()

    expired_subscription = await get_subscription(db_path, "YETI1expired")
    active_subscription = await get_subscription(db_path, "YETI1active")

    assert expired_subscription["subscribed"] is False
    assert expired_subscription["expires_at"] == pytest.approx(current_time - 1.0)
    assert active_subscription["subscribed"] is True
    assert await is_active(db_path, "YETI1expired") is False
    assert await is_active(db_path, "YETI1active") is True

    removed = await expire_old(db_path)

    assert removed == 1
    assert await get_expiry(db_path, "YETI1expired") is None
    assert await get_expiry(db_path, "YETI1active") == pytest.approx(current_time + 60.0)
