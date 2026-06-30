"""
Genesis block (block 0) — the anchor of the YETI chain.

No prev_hash, zero reward, no miner. Coordinator signs it at chain init.
Contains the chain_id so testnet and mainnet chains are permanently distinct.
"""

import time

from .block import Block, CURRENT_VERSION, GENESIS_PREV_HASH, compute_task_content_hash
from .consensus import sign_block

GENESIS_TASK_ID = "genesis"
GENESIS_VOLUNTEER_ID = "coordinator"
GENESIS_TASK_TEXT = "YETI genesis block — chain anchor"


def create_genesis_block(
    chain_id: str,
    coordinator_privkey_hex: str,
    coordinator_wallet: str,
    timestamp: float | None = None,
) -> Block:
    """
    Create and sign the genesis block.

    chain_id:  "yeti-mainnet" or "yeti-testnet"
    coordinator_privkey_hex: hex Ed25519 private key for signing
    coordinator_wallet: YETI1... address (receives no reward — treasury only if desired)
    timestamp: Unix epoch float; defaults to now if None
    """
    ts = timestamp if timestamp is not None else time.time()
    block = Block(
        version=CURRENT_VERSION,
        chain_id=chain_id,
        index=0,
        timestamp=ts,
        prev_hash=GENESIS_PREV_HASH,
        task_id=GENESIS_TASK_ID,
        task_salt="",
        task_content_hash=compute_task_content_hash(GENESIS_TASK_TEXT),
        output_hash="0" * 64,
        difficulty_target="",
        nonce_attempts=0,
        miner_wallet=coordinator_wallet,
        volunteer_id=GENESIS_VOLUNTEER_ID,
        completion_tokens=0,
        prompt_tokens=0,
        benchmark_signature="",
        zk_proof="",
        miner_reward=0.0,
        treasury_reward=0.0,
        coordinator_signature="",
        block_hash="",
    )
    return sign_block(block, coordinator_privkey_hex)
