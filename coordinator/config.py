"""Application configuration for the Soft Yeti coordinator."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve .env relative to this file, regardless of CWD
_HERE = Path(__file__).parent


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and .env."""

    COORDINATOR_ED25519_KEY_PATH: str = str(_HERE / "coordinator.key")
    COORDINATOR_ED25519_PUBLIC_KEY_PATH: str = str(_HERE / "coordinator.pub")
    COORDINATOR_ED25519_KEY_PASS: SecretStr = SecretStr("")
    TREASURY_WALLET: str = "YETI1treasury"
    REWARD_RATE: float = 0.001
    TREASURY_FEE: float = 0.1
    DIFFICULTY_TARGET: str = "0000"
    CANARY_RATE: float = 0.05
    CHAIN_ID: str = "yeti-testnet"
    CHAIN_STORE_PATH: str = str(_HERE / "yeti-chain.jsonl")
    DB_PATH: str = str(_HERE / "coordinator.db")
    API_KEY_HEADER: str = "X-Yeti-API-Key"
    JCLAW_API_KEY: str = ""
    GENERATE_TIMEOUT_S: float = 900.0

    model_config = SettingsConfigDict(
        env_file=str(_HERE / ".env"), env_file_encoding="utf-8"
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
