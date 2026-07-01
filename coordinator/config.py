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
    BASE_RATE: float = 0.0001
    TREASURY_FEE: float = 0.1
    DIFFICULTY_TARGET: str = "0000"
    # Phase 3: mobile tier — inference is slower per-attempt than desktop GPU, so mobile
    # backends get an easier (shorter) target to keep expected-attempts-to-mint comparable.
    DIFFICULTY_TARGET_METAL: str = "00"
    DIFFICULTY_TARGET_VULKAN: str = "00"
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

    def difficulty_for_backend(self, inference_backend: str) -> str:
        """Resolve the difficulty_target for a volunteer's backend, falling back to desktop default."""
        overrides = {
            "metal": self.DIFFICULTY_TARGET_METAL,
            "vulkan": self.DIFFICULTY_TARGET_VULKAN,
        }
        return overrides.get(inference_backend, self.DIFFICULTY_TARGET)


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
