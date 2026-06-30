"""HTTP client for reading the YETI chain node endpoints on the coordinator."""
from __future__ import annotations

import requests


class ChainClient:
    """Read-only client for the coordinator's chain node sub-app."""

    def __init__(self, coordinator_url: str, timeout: float = 10.0) -> None:
        self._base = coordinator_url.rstrip("/")
        self._timeout = timeout

    def get_balance(self, address: str) -> float:
        resp = requests.get(f"{self._base}/chain/balance/{address}", timeout=self._timeout)
        resp.raise_for_status()
        return float(resp.json().get("balance", 0.0))

    def get_history(self, address: str) -> list[dict]:
        resp = requests.get(f"{self._base}/chain/history/{address}", timeout=self._timeout)
        resp.raise_for_status()
        return list(resp.json().get("blocks", []))

    def get_height(self) -> int:
        resp = requests.get(f"{self._base}/chain/height", timeout=self._timeout)
        resp.raise_for_status()
        return int(resp.json().get("height", 0))

    def ping(self) -> bool:
        """Return True if the coordinator health endpoint responds."""
        try:
            resp = requests.get(f"{self._base}/api/health", timeout=self._timeout)
            return resp.status_code == 200
        except Exception:
            return False
