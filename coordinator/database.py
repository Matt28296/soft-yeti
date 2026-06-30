"""Async SQLite database helpers for the Soft Yeti coordinator."""

from collections.abc import AsyncIterator

import aiosqlite


async def init_db(db_path: str) -> None:
    """Initialize coordinator database tables idempotently."""

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS volunteers (
                volunteer_id TEXT PRIMARY KEY,
                miner_wallet TEXT NOT NULL,
                api_key_hash TEXT NOT NULL,
                model_name TEXT,
                vram_gb REAL,
                registered_at REAL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                wallet_address TEXT PRIMARY KEY,
                expires_at REAL NOT NULL
            )
            """
        )
        await db.commit()


async def get_db(db_path: str) -> AsyncIterator[aiosqlite.Connection]:
    """Yield an async SQLite connection and close it after use."""

    db = await aiosqlite.connect(db_path)
    try:
        yield db
    finally:
        await db.close()
