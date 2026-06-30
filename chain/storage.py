"""
Durable chain storage: JSONL append-only log + aiosqlite index.

Write path: append_block() → appends to blocks.jsonl AND inserts into SQLite.
Read path: all queries go through SQLite (fast indexed lookups).
Recovery: if SQLite is absent/corrupt, rebuild_index_from_jsonl() replays the log.

Must use aiosqlite throughout — bare sqlite3 under asyncio causes "database is
locked" errors because asyncio runs in a single thread and sqlite3's default
connection is not async-safe.
"""

import asyncio
import json
import os
from pathlib import Path

import aiosqlite

from .block import Block

BLOCKS_JSONL = "blocks.jsonl"
BLOCKS_DB = "blocks.db"

_CREATE_BLOCKS = """
CREATE TABLE IF NOT EXISTS blocks (
    idx             INTEGER PRIMARY KEY,
    block_hash      TEXT UNIQUE NOT NULL,
    miner_wallet    TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    miner_reward    REAL NOT NULL,
    treasury_reward REAL NOT NULL,
    task_id         TEXT NOT NULL,
    data            TEXT NOT NULL   -- full JSON blob
)
"""

_CREATE_IDX_WALLET = "CREATE INDEX IF NOT EXISTS idx_wallet ON blocks(miner_wallet)"
_CREATE_IDX_TASK = "CREATE INDEX IF NOT EXISTS idx_task ON blocks(task_id)"


class ChainStorage:
    def __init__(self, data_dir: str | Path):
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._jsonl = self._dir / BLOCKS_JSONL
        self._db_path = self._dir / BLOCKS_DB
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(_CREATE_BLOCKS)
        await self._db.execute(_CREATE_IDX_WALLET)
        await self._db.execute(_CREATE_IDX_TASK)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def append_block(self, block: Block) -> None:
        """Append a signed block to JSONL and index it in SQLite atomically."""
        blob = json.dumps(block.to_dict(), separators=(",", ":"))
        async with self._lock:
            # Write to JSONL first (append-only log is the source of truth)
            with open(self._jsonl, "a", encoding="utf-8") as f:
                f.write(blob + "\n")
            # Then index in SQLite
            await self._db.execute(
                """INSERT OR IGNORE INTO blocks
                   (idx, block_hash, miner_wallet, timestamp,
                    miner_reward, treasury_reward, task_id, data)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    block.index,
                    block.block_hash,
                    block.miner_wallet,
                    block.timestamp,
                    block.miner_reward,
                    block.treasury_reward,
                    block.task_id,
                    blob,
                ),
            )
            await self._db.commit()

    async def get_block_by_index(self, index: int) -> Block | None:
        async with self._db.execute(
            "SELECT data FROM blocks WHERE idx=?", (index,)
        ) as cur:
            row = await cur.fetchone()
        return Block.from_dict(json.loads(row["data"])) if row else None

    async def get_block_by_hash(self, block_hash: str) -> Block | None:
        async with self._db.execute(
            "SELECT data FROM blocks WHERE block_hash=?", (block_hash,)
        ) as cur:
            row = await cur.fetchone()
        return Block.from_dict(json.loads(row["data"])) if row else None

    async def get_height(self) -> int:
        """Return total number of blocks in the chain (0 if empty)."""
        async with self._db.execute("SELECT COUNT(*) as c FROM blocks") as cur:
            row = await cur.fetchone()
        return row["c"] if row else 0

    async def get_latest_block(self) -> Block | None:
        async with self._db.execute(
            "SELECT data FROM blocks ORDER BY idx DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        return Block.from_dict(json.loads(row["data"])) if row else None

    async def get_blocks_by_wallet(
        self, wallet: str, limit: int = 50, offset: int = 0
    ) -> list[Block]:
        async with self._db.execute(
            "SELECT data FROM blocks WHERE miner_wallet=? ORDER BY idx DESC LIMIT ? OFFSET ?",
            (wallet, limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [Block.from_dict(json.loads(r["data"])) for r in rows]

    async def get_balance(self, wallet: str) -> float:
        """Sum all miner_reward credits for a wallet."""
        async with self._db.execute(
            "SELECT COALESCE(SUM(miner_reward),0) as bal FROM blocks WHERE miner_wallet=?",
            (wallet,),
        ) as cur:
            row = await cur.fetchone()
        return float(row["bal"]) if row else 0.0

    async def get_treasury_balance(self, treasury_wallet: str) -> float:
        """Sum all treasury_reward credits."""
        async with self._db.execute(
            "SELECT COALESCE(SUM(treasury_reward),0) as bal FROM blocks",
        ) as cur:
            row = await cur.fetchone()
        return float(row["bal"]) if row else 0.0

    async def rebuild_index_from_jsonl(self) -> int:
        """Replay JSONL into a fresh SQLite index. Returns number of blocks replayed."""
        if not self._jsonl.exists():
            return 0
        await self._db.execute("DELETE FROM blocks")
        await self._db.commit()
        count = 0
        with open(self._jsonl, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                block = Block.from_dict(json.loads(line))
                await self._db.execute(
                    """INSERT OR IGNORE INTO blocks
                       (idx, block_hash, miner_wallet, timestamp,
                        miner_reward, treasury_reward, task_id, data)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        block.index,
                        block.block_hash,
                        block.miner_wallet,
                        block.timestamp,
                        block.miner_reward,
                        block.treasury_reward,
                        block.task_id,
                        line,
                    ),
                )
                count += 1
        await self._db.commit()
        return count
