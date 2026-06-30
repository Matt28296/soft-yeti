"""Volunteer registration and API key authentication helpers."""

import secrets
import time

import aiosqlite
import bcrypt
from fastapi import Depends, HTTPException, Request, status

from coordinator.config import Settings, get_settings
from coordinator.schemas import VolunteerRegistration


async def register_volunteer(db_path: str, reg: VolunteerRegistration) -> str:
    """Register a volunteer and return the one-time plaintext API key."""

    raw_key = secrets.token_hex(32)
    api_key_hash = bcrypt.hashpw(raw_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO volunteers (
                volunteer_id,
                miner_wallet,
                api_key_hash,
                model_name,
                vram_gb,
                miner_pubkey,
                registered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reg.volunteer_id,
                reg.miner_wallet,
                api_key_hash,
                reg.model_name,
                reg.vram_gb,
                reg.miner_pubkey,
                time.time(),
            ),
        )
        await db.commit()

    return raw_key


async def get_volunteer_security_info(
    db_path: str,
    volunteer_id: str,
) -> tuple[str, str] | None:
    """Return (miner_pubkey, model_name) for a registered volunteer, or None if not found."""

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT miner_pubkey, model_name FROM volunteers WHERE volunteer_id = ?",
            (volunteer_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        return None
    return str(row[0] or ""), str(row[1] or "")


async def verify_api_key(db_path: str, volunteer_id: str, raw_key: str) -> bool:
    """Verify a volunteer_id/raw API key pair against the stored bcrypt hash."""

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT api_key_hash FROM volunteers WHERE volunteer_id = ?",
            (volunteer_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        return False

    stored_hash = row[0]
    return bcrypt.checkpw(raw_key.encode("utf-8"), stored_hash.encode("utf-8"))


async def get_current_volunteer(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str:
    """FastAPI dependency returning the authenticated volunteer id."""

    credentials = request.headers.get("Authorization")
    if credentials is None:
        credentials = request.headers.get(settings.API_KEY_HEADER)

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )

    if credentials.startswith("Bearer "):
        credentials = credentials.removeprefix("Bearer ").strip()

    volunteer_id, separator, raw_key = credentials.partition(":")
    if not separator or not volunteer_id or not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format",
        )

    if not await verify_api_key(settings.DB_PATH, volunteer_id, raw_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return volunteer_id
