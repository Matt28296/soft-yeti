"""Subscription tracking helpers for YETI transfer-based access."""

import asyncio
import time

import aiosqlite

from coordinator.schemas import TransferNotification


TIER_DAYS = {"basic": 30, "pro": 90, "enterprise": 365}
_wallet_locks: dict[str, asyncio.Lock] = {}
_wallet_locks_guard = asyncio.Lock()


def _tier_for_amount(amount: float) -> str:
    """Return the subscription tier unlocked by a transfer amount."""

    if amount < 7500:
        return "basic"
    if amount < 25000:
        return "pro"
    return "enterprise"


async def _get_lock(wallet_address: str) -> asyncio.Lock:
    """Return the per-wallet lock used to serialize subscription updates."""

    async with _wallet_locks_guard:
        if wallet_address not in _wallet_locks:
            _wallet_locks[wallet_address] = asyncio.Lock()
        return _wallet_locks[wallet_address]


async def record_transfer(db_path: str, transfer: TransferNotification) -> None:
    """Record a paid transfer and extend the recipient wallet subscription."""

    wallet_lock = await _get_lock(transfer.to_wallet)
    async with wallet_lock:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT expires_at FROM subscriptions WHERE wallet_address = ?",
                (transfer.to_wallet,),
            )
            row = await cursor.fetchone()
            await cursor.close()

            now = time.time()
            base_expires_at = max(float(row[0]), now) if row else now
            tier = _tier_for_amount(transfer.amount)
            expires_at = base_expires_at + (TIER_DAYS[tier] * 86400)

            await db.execute(
                """
                INSERT OR REPLACE INTO subscriptions (wallet_address, expires_at)
                VALUES (?, ?)
                """,
                (transfer.to_wallet, expires_at),
            )
            await db.commit()


async def get_subscription(db_path: str, wallet_address: str) -> dict[str, float | bool | str | None]:
    """Return subscription state for a wallet with active status computed from expiry."""

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT expires_at FROM subscriptions WHERE wallet_address = ?",
            (wallet_address,),
        )
        row = await cursor.fetchone()
        await cursor.close()

    expires_at = float(row[0]) if row else None
    return {
        "wallet_address": wallet_address,
        "subscribed": expires_at is not None and expires_at > time.time(),
        "expires_at": expires_at,
    }


async def is_active(db_path: str, wallet_address: str) -> bool:
    """Return True when the wallet has a non-expired subscription."""

    subscription = await get_subscription(db_path, wallet_address)
    return bool(subscription["subscribed"])


async def expire_old(db_path: str) -> int:
    """Delete expired subscriptions and return the number of removed rows."""

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "DELETE FROM subscriptions WHERE expires_at <= ?",
            (time.time(),),
        )
        removed = cursor.rowcount
        await cursor.close()
        await db.commit()
    return int(removed if removed is not None else 0)


async def is_subscribed(db_path: str, wallet_address: str) -> bool:
    """Backward-compatible alias for is_active."""

    return await is_active(db_path, wallet_address)


async def get_expiry(db_path: str, wallet_address: str) -> float | None:
    """Return the wallet subscription expiry timestamp, if present."""

    subscription = await get_subscription(db_path, wallet_address)
    expires_at = subscription["expires_at"]
    return float(expires_at) if expires_at is not None else None
