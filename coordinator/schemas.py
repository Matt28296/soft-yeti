"""Pydantic schemas for the Soft Yeti coordinator API."""

from pydantic import BaseModel, ConfigDict, Field


class TaskRequest(BaseModel):
    """Client request to create or assign an inference task."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    task_type: str
    prompt: str
    max_tokens: int = 512


class TaskAssignment(TaskRequest):
    """Task payload assigned to a volunteer miner."""

    system: str = ""
    temperature: float = 0.3
    task_salt: str
    difficulty_target: str
    is_canary: bool = False
    canary_task_id: str | None = None


class InferenceSubmission(BaseModel):
    """Volunteer proof-of-inference submission."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    volunteer_id: str
    miner_wallet: str
    miner_pubkey: str
    miner_signature: str
    model_name: str
    output_text: str
    output_hash: str
    nonce_attempts: int = Field(ge=1)
    benchmark_signature: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    task_salt: str
    # Phase 1.5: accumulated across all nonce attempts for base-rate reward
    total_completion_tokens: int = Field(ge=0, default=0)
    # Phase 1.5: all attempt outputs so coordinator can deliver the best one to J-Claw
    all_outputs: list[str] = Field(default_factory=list)


class VolunteerRegistration(BaseModel):
    """Registration payload for a volunteer miner."""

    model_config = ConfigDict(extra="forbid")

    volunteer_id: str
    miner_wallet: str
    miner_pubkey: str
    model_name: str
    vram_gb: float = Field(ge=0)


class HeartbeatRequest(BaseModel):
    """Heartbeat payload for keeping volunteer presence fresh."""

    model_config = ConfigDict(extra="forbid")

    volunteer_id: str


class TransferNotification(BaseModel):
    """Blockchain transfer notification used to activate subscriptions."""

    model_config = ConfigDict(extra="forbid")

    from_wallet: str
    to_wallet: str
    amount: float = Field(gt=0)
    block_index: int = Field(ge=0)


class SubscriptionStatus(BaseModel):
    """Subscription status response for a wallet."""

    model_config = ConfigDict(extra="forbid")

    wallet_address: str
    subscribed: bool
    expires_at: float | None = None


class YetiBlock(BaseModel):
    """Minted YETI proof-of-inference block payload."""

    model_config = ConfigDict(extra="forbid")

    version: int
    chain_id: str
    index: int = Field(ge=0)
    timestamp: float
    prev_hash: str
    task_id: str
    task_salt: str
    task_content_hash: str
    output_hash: str
    difficulty_target: str
    nonce_attempts: int = Field(ge=0)
    miner_wallet: str
    miner_pubkey: str = ""
    volunteer_id: str
    completion_tokens: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    benchmark_signature: str
    model_name: str = ""
    zk_proof: str = ""
    total_completion_tokens: int = Field(ge=0, default=0)
    base_reward: float = Field(ge=0, default=0.0)
    miner_reward: float = Field(ge=0)
    treasury_reward: float = Field(ge=0)
    coordinator_signature: str
    block_hash: str


class GenerateRequest(BaseModel):
    """J-Claw request for volunteer inference via the YETI pool."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    task_type: str
    system: str = ""
    prompt: str
    max_tokens: int = 8192
    temperature: float = 0.15


class GenerateResponse(BaseModel):
    """Response from a completed volunteer inference task."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    output: str


class SubmitResponse(BaseModel):
    """Submission verification and minting response."""

    model_config = ConfigDict(extra="forbid")

    accepted: bool
    reason: str
    block_index: int | None = None
    miner_reward: float | None = None
