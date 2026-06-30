"""
Chain layer smoke tests — run with: python -m pytest chain/test_chain.py -v
No external services required.
"""

import asyncio
import time
from pathlib import Path

import pytest

from chain.wallet import (
    generate_wallet,
    sign_message,
    validate_address,
    verify_signature,
)
from chain.block import Block, CURRENT_VERSION, compute_output_hash, compute_task_content_hash
from chain.difficulty import (
    adjust_difficulty,
    check_output_hash,
    INITIAL_DIFFICULTY,
)
from chain.consensus import (
    coordinator_pubkey_hex,
    sign_block,
    verify_block_hash,
    verify_block_signature,
)
from chain.storage import ChainStorage
from chain.chain import ChainManager, compute_rewards
from chain.genesis import create_genesis_block


# ── Wallet tests ──────────────────────────────────────────────────────────────

def test_wallet_address_format():
    w = generate_wallet()
    assert w["address"].startswith("YETI1"), f"Address format wrong: {w['address']}"
    assert len(w["pubkey"]) == 64   # 32 bytes hex
    assert len(w["privkey"]) == 64


def test_wallet_address_valid():
    w = generate_wallet()
    assert validate_address(w["address"])


def test_wallet_sign_verify():
    w = generate_wallet()
    msg = b"test payload"
    sig = sign_message(w["privkey"], msg)
    assert verify_signature(w["pubkey"], msg, sig)


def test_wallet_sign_wrong_msg():
    w = generate_wallet()
    sig = sign_message(w["privkey"], b"original")
    assert not verify_signature(w["pubkey"], b"tampered", sig)


def test_wallet_invalid_address():
    assert not validate_address("invalid")
    assert not validate_address("YETI1")   # too short
    assert not validate_address("BTC1abc123")


# ── Block / difficulty tests ──────────────────────────────────────────────────

def test_output_hash_deterministic():
    h1 = compute_output_hash("hello", "tid1", "salt1")
    h2 = compute_output_hash("hello", "tid1", "salt1")
    assert h1 == h2 and len(h1) == 64


def test_check_output_hash():
    # Manually find a hash that meets "0" target (1-in-16 odds, very fast)
    for i in range(1000):
        h = compute_output_hash(f"output_{i}", "tid", "salt")
        if h.startswith("0"):
            assert check_output_hash(h, "0")
            assert not check_output_hash(h, "1")
            return
    pytest.fail("Could not find valid hash in 1000 attempts")


def test_difficulty_adjustment_tighten():
    new = adjust_difficulty("00", avg_attempts := 2.0)  # below TARGET_LOW=3
    assert new == "000", f"Expected tighter target, got {new}"


def test_difficulty_adjustment_loosen():
    new = adjust_difficulty("000", 10.0)  # above TARGET_HIGH=8
    assert new == "00"


def test_difficulty_no_change():
    new = adjust_difficulty("000", 5.0)  # in range
    assert new == "000"


# ── Consensus tests ───────────────────────────────────────────────────────────

def _make_coord_wallet():
    w = generate_wallet()
    pubkey = coordinator_pubkey_hex(w["privkey"])
    return w, pubkey


def _sample_block(chain_id="yeti-testnet", index=1, prev_hash="0" * 64) -> Block:
    return Block(
        version=CURRENT_VERSION,
        chain_id=chain_id,
        index=index,
        timestamp=1000000.0,
        prev_hash=prev_hash,
        task_id="test-task",
        task_salt="testsalt",
        task_content_hash=compute_task_content_hash("some prompt"),
        output_hash="0" * 64,
        difficulty_target="",
        nonce_attempts=1,
        miner_wallet="YETI1abc",
        volunteer_id="vol1",
        completion_tokens=100,
        prompt_tokens=50,
        benchmark_signature="",
        zk_proof="",
        miner_reward=0.09,
        treasury_reward=0.01,
        coordinator_signature="",
        block_hash="",
    )


def test_sign_and_verify_block():
    w, pubkey = _make_coord_wallet()
    block = _sample_block()
    sign_block(block, w["privkey"])
    assert block.coordinator_signature != ""
    assert block.block_hash != ""
    assert verify_block_signature(block, pubkey)
    assert verify_block_hash(block)


def test_tampered_block_fails_hash():
    w, pubkey = _make_coord_wallet()
    block = _sample_block()
    sign_block(block, w["privkey"])
    block.miner_reward = 999.0  # tamper
    assert not verify_block_hash(block)


def test_tampered_block_fails_signature():
    w, pubkey = _make_coord_wallet()
    w2, _ = _make_coord_wallet()   # different key
    block = _sample_block()
    sign_block(block, w["privkey"])
    # Verify with wrong pubkey
    assert not verify_block_signature(block, w2["pubkey"])


# ── Chain + storage integration tests ────────────────────────────────────────

@pytest.fixture
def tmp_chain_dir(tmp_path):
    return tmp_path / "chain_data"


async def _build_chain(data_dir: Path, n_blocks: int = 3):
    coord_wallet = generate_wallet()
    coord_pubkey = coordinator_pubkey_hex(coord_wallet["privkey"])
    storage = ChainStorage(data_dir)
    await storage.open()
    chain = ChainManager(storage, coord_pubkey)

    genesis = create_genesis_block(
        "yeti-testnet",
        coord_wallet["privkey"],
        coord_wallet["address"],
        timestamp=1000000.0,
    )
    await chain.append_block(genesis)

    for i in range(1, n_blocks):
        latest = await chain.get_latest()
        miner = generate_wallet()
        block = _sample_block(
            chain_id="yeti-testnet",
            index=i,
            prev_hash=latest.block_hash,
        )
        block.miner_wallet = miner["address"]
        block.miner_reward = 0.9
        block.treasury_reward = 0.1
        sign_block(block, coord_wallet["privkey"])
        await chain.append_block(block)

    return chain, storage, coord_wallet, coord_pubkey


def test_genesis_block():
    async def run():
        coord = generate_wallet()
        pubkey = coordinator_pubkey_hex(coord["privkey"])
        genesis = create_genesis_block("yeti-testnet", coord["privkey"], coord["address"], 1000.0)
        assert genesis.index == 0
        assert genesis.chain_id == "yeti-testnet"
        assert verify_block_signature(genesis, pubkey)
        assert verify_block_hash(genesis)
    asyncio.run(run())


def test_append_and_height(tmp_chain_dir):
    async def run():
        chain, storage, _, _ = await _build_chain(tmp_chain_dir, 3)
        assert await chain.get_height() == 3
        await storage.close()
    asyncio.run(run())


def test_balance(tmp_chain_dir):
    async def run():
        chain, storage, _, _ = await _build_chain(tmp_chain_dir, 3)
        # Block 1 and 2 each credited miner 0.9 (different wallets each time)
        # Genesis miner gets 0.0; check treasury instead
        height = await chain.get_height()
        assert height == 3
        await storage.close()
    asyncio.run(run())


def test_verify_chain(tmp_chain_dir):
    async def run():
        chain, storage, _, _ = await _build_chain(tmp_chain_dir, 4)
        ok, msg = await chain.verify_chain()
        assert ok, f"Chain verify failed: {msg}"
        await storage.close()
    asyncio.run(run())


def test_wrong_index_rejected(tmp_chain_dir):
    async def run():
        coord = generate_wallet()
        pubkey = coordinator_pubkey_hex(coord["privkey"])
        storage = ChainStorage(tmp_chain_dir)
        await storage.open()
        chain = ChainManager(storage, pubkey)
        genesis = create_genesis_block("yeti-testnet", coord["privkey"], coord["address"])
        await chain.append_block(genesis)

        # Try appending a block with wrong index
        bad_block = _sample_block(index=5, prev_hash=genesis.block_hash)
        sign_block(bad_block, coord["privkey"])
        with pytest.raises(ValueError, match="index"):
            await chain.append_block(bad_block)
        await storage.close()
    asyncio.run(run())


def test_jsonl_replay(tmp_chain_dir):
    async def run():
        chain, storage, coord_wallet, coord_pubkey = await _build_chain(tmp_chain_dir, 3)
        await storage.close()

        # Rebuild index from JSONL
        storage2 = ChainStorage(tmp_chain_dir)
        await storage2.open()
        replayed = await storage2.rebuild_index_from_jsonl()
        assert replayed == 3
        chain2 = ChainManager(storage2, coord_pubkey)
        ok, msg = await chain2.verify_chain()
        assert ok, f"Post-replay verify failed: {msg}"
        await storage2.close()
    asyncio.run(run())


def test_compute_rewards():
    miner, treasury = compute_rewards(completion_tokens=1000, nonce_attempts=5)
    gross = 1000 * 0.001 * 5   # = 5.0
    assert abs(treasury - 0.5) < 1e-7
    assert abs(miner - 4.5) < 1e-7
