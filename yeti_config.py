"""Soft Yeti volunteer client configuration (~/.soft_yeti/config.json)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".soft_yeti" / "config.json"


@dataclass
class YetiConfig:
    coordinator_url: str = "http://localhost:8000"
    volunteer_id: str = ""
    model_name: str = "qwen2.5-coder:7b-instruct"
    vram_gb: float = 0.0
    wallet_path: str = str(Path.home() / ".soft_yeti" / "wallet.json")
    api_key: str = ""
    enabled: bool = False
    ollama_host: str = "http://localhost:11434"
    heartbeat_interval_s: int = 20
    task_poll_interval_s: float = 2.0
    max_nonce_attempts: int = 10000

    def save(self, path: Path = DEFAULT_CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> "YetiConfig":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        valid_keys = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})
