"""In-memory volunteer registry for coordinator liveness tracking."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


def utc_timestamp() -> float:
    """Return the current UTC timestamp as epoch seconds."""
    return datetime.now(UTC).timestamp()


@dataclass
class VolunteerRecord:
    volunteer_id: str
    model_name: str = ""
    vram_gb: float = 0.0
    miner_wallet: str = ""
    registered_at: float = field(default_factory=utc_timestamp)
    last_seen: float = field(default_factory=utc_timestamp)
    tasks_completed: int = 0
    failure_count: int = 0
    last_failure: float | None = None
    active: bool = True


MAX_FAILURE_COUNT = 10


class VolunteerRegistry:
    """Tracks volunteer heartbeats and health in memory."""

    def __init__(self, default_ttl: float = 60.0) -> None:
        self.default_ttl = default_ttl
        self._lock = asyncio.Lock()
        self._volunteers: dict[str, VolunteerRecord] = {}

    async def register_seen(
        self,
        volunteer_id: str,
        model_name: str = "",
        vram_gb: float = 0.0,
        miner_wallet: str = "",
    ) -> VolunteerRecord:
        """Create or refresh a volunteer record with the current UTC timestamp."""
        now = utc_timestamp()
        async with self._lock:
            record = self._volunteers.get(volunteer_id)
            if record is None:
                record = VolunteerRecord(
                    volunteer_id=volunteer_id,
                    model_name=model_name,
                    vram_gb=vram_gb,
                    miner_wallet=miner_wallet,
                    registered_at=now,
                    last_seen=now,
                )
                self._volunteers[volunteer_id] = record
            else:
                record.last_seen = now
                record.active = True
                if model_name:
                    record.model_name = model_name
                if vram_gb:
                    record.vram_gb = vram_gb
                if miner_wallet:
                    record.miner_wallet = miner_wallet
            return record

    async def heartbeat(self, volunteer_id: str) -> bool:
        """Update a volunteer heartbeat timestamp if the volunteer exists."""
        now = utc_timestamp()
        async with self._lock:
            record = self._volunteers.get(volunteer_id)
            if record is None:
                return False
            record.last_seen = now
            record.active = True
            return True

    async def mark_failure(self, volunteer_id: str) -> bool:
        """Record a failed volunteer action; deactivate after too many failures."""
        now = utc_timestamp()
        async with self._lock:
            record = self._volunteers.get(volunteer_id)
            if record is None:
                return False
            record.failure_count += 1
            record.last_failure = now
            if record.failure_count >= MAX_FAILURE_COUNT:
                record.active = False
            return True

    def healthy_volunteers(self, ttl: float | None = None) -> list[VolunteerRecord]:
        """Return active volunteers seen within the TTL window."""
        max_age = self.default_ttl if ttl is None else ttl
        cutoff = utc_timestamp() - max_age
        return [
            record
            for record in self._volunteers.values()
            if record.active and record.last_seen >= cutoff
        ]

    def snapshot(self) -> dict[str, dict[str, object]]:
        """Return a serializable snapshot of all tracked volunteers."""
        return {
            volunteer_id: asdict(record)
            for volunteer_id, record in self._volunteers.items()
        }
