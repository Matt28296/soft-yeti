"""
Difficulty management for Proof-of-Inference-as-Nonce.

Difficulty is expressed as a hex prefix that output_hash must start with.
"000" → 1-in-4096 chance per inference run → target ~3-5 attempts per task.

Adjustment: every EPOCH_SIZE blocks, measure avg nonce_attempts over the epoch.
If avg < TARGET_LOW: tighten (add a hex digit). If avg > TARGET_HIGH: loosen.
Conservative — only ever adjusts by one character at a time.
"""

from typing import Sequence

TARGET_LOW = 3          # if avg attempts below this, tighten difficulty
TARGET_HIGH = 8         # if avg attempts above this, loosen difficulty
EPOCH_SIZE = 500        # blocks between difficulty reviews
INITIAL_DIFFICULTY = "00"   # ~1-in-256 per attempt → easy for early testnet


def check_output_hash(output_hash: str, difficulty_target: str) -> bool:
    """
    Return True if output_hash satisfies difficulty_target.
    difficulty_target is a hex prefix string the hash must start with.
    """
    return output_hash.startswith(difficulty_target)


def adjust_difficulty(current_target: str, epoch_avg_attempts: float) -> str:
    """
    Adjust difficulty based on observed avg nonce_attempts over the last epoch.

    Returns a new difficulty_target string (never shorter than 1 char or
    longer than 8 chars — practical bounds for ~1-in-4B max difficulty).
    """
    if epoch_avg_attempts < TARGET_LOW and len(current_target) < 8:
        return current_target + "0"
    if epoch_avg_attempts > TARGET_HIGH and len(current_target) > 1:
        return current_target[:-1]
    return current_target


def epoch_avg_attempts(nonce_attempts_list: Sequence[int]) -> float:
    """Average nonce_attempts over a block epoch."""
    if not nonce_attempts_list:
        return 0.0
    return sum(nonce_attempts_list) / len(nonce_attempts_list)


def expected_attempts(difficulty_target: str) -> float:
    """
    Expected number of inference runs to find a valid hash for a given target.
    Each hex char narrows the space by 1/16, so expected = 16^len(target).
    """
    return 16 ** len(difficulty_target)


def difficulty_to_bits(difficulty_target: str) -> int:
    """Approximate difficulty in bits (each hex char = 4 bits of leading zeros)."""
    return len(difficulty_target) * 4
