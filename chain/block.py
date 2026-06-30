"""
YETI block — the unit of the chain. One block = one verified task completion.

Block hash = SHA-256 of all fields (including coordinator_signature) serialized
deterministically as sorted JSON. This makes the hash a content-addressable
fingerprint of the complete block record.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field


@dataclass
class Block:
    # Protocol
    version: int                # increments on protocol upgrades; current = 1
    chain_id: str               # "yeti-mainnet" | "yeti-testnet" — prevents replay

    # Chain linkage
    index: int                  # block height (0 = genesis)
    timestamp: float            # Unix epoch seconds (float for sub-second precision)
    prev_hash: str              # block_hash of the preceding block; "" for genesis

    # Task identification
    task_id: str                # UUID assigned by coordinator
    task_salt: str              # coordinator-generated per-task salt for hash puzzle
    task_content_hash: str      # SHA-256(sanitized prompt text) — links block to exact input

    # Proof-of-Inference nonce fields
    output_hash: str            # SHA-256(output_text + task_id + task_salt) — THE NONCE
    difficulty_target: str      # hex prefix that output_hash must start with (e.g. "000")
    nonce_attempts: int         # inference runs needed to satisfy difficulty_target

    # Miner identity
    miner_wallet: str           # YETI1... address
    volunteer_id: str           # volunteer's registered identifier
    completion_tokens: int      # output tokens produced
    prompt_tokens: int          # input tokens consumed

    # Verification fields
    benchmark_signature: str    # GPU micro-benchmark timing blob (Theory 7); "" in Phase 0
    zk_proof: str               # zkML proof placeholder for Phase 4; always "" now

    # Rewards
    miner_reward: float         # YETI credited to miner_wallet
    treasury_reward: float      # YETI credited to coordinator treasury

    # Auth (set last — computed over all above)
    coordinator_signature: str  # Ed25519 hex sig over canonical_bytes(); "" before signing
    block_hash: str             # SHA-256(canonical_bytes()) including coordinator_signature

    @staticmethod
    def _serializable(d: dict) -> dict:
        """Ensure all values are JSON-serializable (floats stay floats)."""
        return d

    def signing_payload(self) -> bytes:
        """
        The bytes the coordinator signs.
        Excludes both coordinator_signature and block_hash — coordinator_signature
        is empty at sign time, so it must not be in the payload or verification
        would need to reconstruct the empty-sig state.
        """
        d = asdict(self)
        d.pop("block_hash")
        d.pop("coordinator_signature")
        return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()

    def canonical_bytes(self) -> bytes:
        """
        Deterministic serialization for block_hash computation.
        Includes coordinator_signature (set after signing), excludes block_hash
        (that's what we're computing).
        """
        d = asdict(self)
        d.pop("block_hash")
        return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()

    def compute_hash(self) -> str:
        """SHA-256 of canonical_bytes (includes coordinator_signature)."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def finalize(self) -> "Block":
        """Set block_hash from current field values. Call after signing."""
        self.block_hash = self.compute_hash()
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Block":
        return cls(**d)


def compute_output_hash(output_text: str, task_id: str, task_salt: str) -> str:
    """The PoI nonce: SHA-256(output_text + task_id + task_salt)."""
    payload = (output_text + task_id + task_salt).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_task_content_hash(sanitized_prompt: str) -> str:
    """SHA-256 of the sanitized prompt — links a block to its exact input."""
    return hashlib.sha256(sanitized_prompt.encode("utf-8")).hexdigest()


CURRENT_VERSION = 1
GENESIS_PREV_HASH = "0" * 64
