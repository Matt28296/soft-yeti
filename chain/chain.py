"""
Chain operations: append, verify integrity, balance queries, history.

ChainManager wraps ChainStorage and enforces chain invariants:
  - Each block's prev_hash must equal the previous block's block_hash
  - Each block's block_hash must verify (content hash + coordinator signature)
  - Index must be strictly monotonic
"""

from .block import Block, GENESIS_PREV_HASH
from .consensus import verify_block_hash, verify_block_signature
from .storage import ChainStorage

REWARD_RATE = 0.001         # YETI per completion_token per nonce_attempt
TREASURY_FEE = 0.10         # 10% of gross reward goes to treasury


def compute_rewards(completion_tokens: int, nonce_attempts: int) -> tuple[float, float]:
    """
    Compute (miner_reward, treasury_reward) for a block.
    gross = completion_tokens * REWARD_RATE * nonce_attempts
    miner gets (1 - TREASURY_FEE) of gross; treasury gets TREASURY_FEE.
    """
    gross = completion_tokens * REWARD_RATE * nonce_attempts
    treasury = round(gross * TREASURY_FEE, 8)
    miner = round(gross - treasury, 8)
    return miner, treasury


class ChainManager:
    def __init__(self, storage: ChainStorage, coordinator_pubkey_hex: str):
        self._storage = storage
        self._coord_pubkey = coordinator_pubkey_hex

    async def append_block(self, block: Block) -> None:
        """
        Append a block after validating chain linkage and signature.
        Raises ValueError with a descriptive message on any validation failure.
        """
        height = await self._storage.get_height()
        latest = await self._storage.get_latest_block()

        # Genesis block
        if height == 0:
            if block.index != 0:
                raise ValueError(f"First block must have index 0, got {block.index}")
            if block.prev_hash != GENESIS_PREV_HASH:
                raise ValueError("Genesis block prev_hash must be all zeros")
        else:
            expected_index = latest.index + 1
            if block.index != expected_index:
                raise ValueError(
                    f"Expected block index {expected_index}, got {block.index}"
                )
            if block.prev_hash != latest.block_hash:
                raise ValueError(
                    f"Block prev_hash mismatch: expected {latest.block_hash[:12]}..., "
                    f"got {block.prev_hash[:12]}..."
                )

        if not verify_block_hash(block):
            raise ValueError(f"Block hash invalid for block {block.index}")

        if not verify_block_signature(block, self._coord_pubkey):
            raise ValueError(
                f"Coordinator signature invalid for block {block.index}"
            )

        await self._storage.append_block(block)

    async def verify_chain(self) -> tuple[bool, str]:
        """
        Walk the full chain verifying linkage, hashes, and signatures.
        Returns (True, "ok") or (False, error_message).
        """
        height = await self._storage.get_height()
        prev_hash = GENESIS_PREV_HASH
        for i in range(height):
            block = await self._storage.get_block_by_index(i)
            if block is None:
                return False, f"Missing block at index {i}"
            if block.prev_hash != prev_hash:
                return False, f"Chain break at index {i}: prev_hash mismatch"
            if not verify_block_hash(block):
                return False, f"Block hash invalid at index {i}"
            if not verify_block_signature(block, self._coord_pubkey):
                return False, f"Coordinator signature invalid at index {i}"
            prev_hash = block.block_hash
        return True, "ok"

    async def get_balance(self, wallet: str) -> float:
        return await self._storage.get_balance(wallet)

    async def get_history(
        self, wallet: str, limit: int = 50, offset: int = 0
    ) -> list[Block]:
        return await self._storage.get_blocks_by_wallet(wallet, limit, offset)

    async def get_height(self) -> int:
        return await self._storage.get_height()

    async def get_block(self, index: int) -> Block | None:
        return await self._storage.get_block_by_index(index)

    async def get_latest(self) -> Block | None:
        return await self._storage.get_latest_block()
