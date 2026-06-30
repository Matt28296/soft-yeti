"""Unit tests for coordinator.auth — registration ownership protection."""

from __future__ import annotations

import pytest

from coordinator.auth import register_volunteer, verify_api_key
from coordinator.database import init_db
from coordinator.schemas import VolunteerRegistration


def _reg(
    volunteer_id: str = "vol-001",
    miner_wallet: str = "YETI1wallet",
    miner_pubkey: str = "aa" * 32,
    model_name: str = "qwen2.5-coder:7b-instruct",
    vram_gb: float = 8.0,
) -> VolunteerRegistration:
    return VolunteerRegistration(
        volunteer_id=volunteer_id,
        miner_wallet=miner_wallet,
        miner_pubkey=miner_pubkey,
        model_name=model_name,
        vram_gb=vram_gb,
    )


@pytest.mark.asyncio
async def test_register_new_volunteer_returns_api_key(tmp_path) -> None:
    db = str(tmp_path / "coordinator.db")
    await init_db(db)
    api_key = await register_volunteer(db, _reg())
    assert api_key
    assert await verify_api_key(db, "vol-001", api_key)


@pytest.mark.asyncio
async def test_reregister_same_identity_rotates_api_key(tmp_path) -> None:
    """Restart re-registration with matching wallet+pubkey issues a new key."""
    db = str(tmp_path / "coordinator.db")
    await init_db(db)
    old_key = await register_volunteer(db, _reg())
    new_key = await register_volunteer(db, _reg())
    assert new_key != old_key
    assert not await verify_api_key(db, "vol-001", old_key)
    assert await verify_api_key(db, "vol-001", new_key)


@pytest.mark.asyncio
async def test_reregister_different_wallet_raises(tmp_path) -> None:
    """Attempt to steal volunteer_id by changing miner_wallet is rejected."""
    db = str(tmp_path / "coordinator.db")
    await init_db(db)
    await register_volunteer(db, _reg(miner_wallet="YETI1original"))
    with pytest.raises(ValueError, match="already registered"):
        await register_volunteer(db, _reg(miner_wallet="YETI1attacker"))


@pytest.mark.asyncio
async def test_reregister_different_pubkey_raises(tmp_path) -> None:
    """Attempt to hijack volunteer_id by changing miner_pubkey is rejected."""
    db = str(tmp_path / "coordinator.db")
    await init_db(db)
    await register_volunteer(db, _reg(miner_pubkey="aa" * 32))
    with pytest.raises(ValueError, match="already registered"):
        await register_volunteer(db, _reg(miner_pubkey="bb" * 32))


@pytest.mark.asyncio
async def test_different_volunteer_ids_coexist(tmp_path) -> None:
    """Two distinct volunteer_ids register without conflict."""
    db = str(tmp_path / "coordinator.db")
    await init_db(db)
    key_a = await register_volunteer(db, _reg(volunteer_id="vol-A"))
    key_b = await register_volunteer(db, _reg(volunteer_id="vol-B", miner_wallet="YETI1walletB"))
    assert await verify_api_key(db, "vol-A", key_a)
    assert await verify_api_key(db, "vol-B", key_b)
