"""Deterministic canary tasks for verifier confidence checks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Final


@dataclass(frozen=True)
class CanaryTask:
    canary_id: str
    prompt: str
    expected_output: str


CANARY_TASKS: Final[list[CanaryTask]] = [
    CanaryTask(
        canary_id="canary-001",
        prompt="Return exactly the result of 2 + 2 as a single number.",
        expected_output="4",
    ),
    CanaryTask(
        canary_id="canary-002",
        prompt="Return exactly the lowercase word for the color of a clear daytime sky.",
        expected_output="blue",
    ),
    CanaryTask(
        canary_id="canary-003",
        prompt="Return exactly the Python expression result: len('yeti').",
        expected_output="4",
    ),
    CanaryTask(
        canary_id="canary-004",
        prompt="Return exactly the next integer after 41.",
        expected_output="42",
    ),
    CanaryTask(
        canary_id="canary-005",
        prompt="Return exactly the string produced by '-'.join(['soft', 'yeti']).",
        expected_output="soft-yeti",
    ),
    CanaryTask(
        canary_id="canary-006",
        prompt="Return exactly the boolean result of Python: 3 > 1.",
        expected_output="True",
    ),
    CanaryTask(
        canary_id="canary-007",
        prompt="Return exactly the first three letters of 'coordinator'.",
        expected_output="coo",
    ),
    CanaryTask(
        canary_id="canary-008",
        prompt="Return exactly the sum of 10 and 15 as a single number.",
        expected_output="25",
    ),
    CanaryTask(
        canary_id="canary-009",
        prompt="Return exactly the uppercase form of 'yeti'.",
        expected_output="YETI",
    ),
    CanaryTask(
        canary_id="canary-010",
        prompt="Return exactly the result of 9 // 2 in Python.",
        expected_output="4",
    ),
]


def _seed_digest(seed: str | int | bytes) -> int:
    if isinstance(seed, bytes):
        seed_bytes = seed
    else:
        seed_bytes = str(seed).encode("utf-8")
    return int.from_bytes(hashlib.sha256(seed_bytes).digest(), "big")


def should_inject(rate: float, seed: str | int | bytes) -> bool:
    """Return a deterministic injection decision for a rate in [0.0, 1.0]."""
    if rate <= 0.0:
        return False
    if rate >= 1.0:
        return True
    threshold = int(rate * (1 << 256))
    return _seed_digest(seed) < threshold


def choose_canary(seed: str | int | bytes) -> CanaryTask:
    """Choose the same canary for the same seed every time."""
    return CANARY_TASKS[_seed_digest(seed) % len(CANARY_TASKS)]


def verify_canary_output(canary: CanaryTask, actual_output: str) -> bool:
    """Validate the canary with exact output comparison."""
    return actual_output == canary.expected_output
