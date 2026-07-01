"""Deterministic canary tasks for verifier confidence checks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Final


@dataclass(frozen=True)
class CanaryTask:
    canary_id: str
    prompt: str
    expected_output: str


CANARY_TASKS: Final[list[CanaryTask]] = [
    # ── Arithmetic (001-010) ──────────────────────────────────────────────────
    CanaryTask(
        canary_id="canary-001",
        prompt="Return exactly the result of 2 + 2 as a single number. No explanation.",
        expected_output="4",
    ),
    CanaryTask(
        canary_id="canary-002",
        prompt="Return exactly the result of 7 * 8 as a single number. No explanation.",
        expected_output="56",
    ),
    CanaryTask(
        canary_id="canary-003",
        prompt="Return exactly the result of 100 - 37 as a single number. No explanation.",
        expected_output="63",
    ),
    CanaryTask(
        canary_id="canary-004",
        prompt="Return exactly the result of 2 ** 8 as a single number. No explanation.",
        expected_output="256",
    ),
    CanaryTask(
        canary_id="canary-005",
        prompt="Return exactly the result of 15 % 4 as a single number. No explanation.",
        expected_output="3",
    ),
    CanaryTask(
        canary_id="canary-006",
        prompt="Return exactly the result of 17 + 25 as a single number. No explanation.",
        expected_output="42",
    ),
    CanaryTask(
        canary_id="canary-007",
        prompt="Return exactly the result of 81 // 9 as a single number. No explanation.",
        expected_output="9",
    ),
    CanaryTask(
        canary_id="canary-008",
        prompt="Return exactly the result of 144 // 12 as a single number. No explanation.",
        expected_output="12",
    ),
    CanaryTask(
        canary_id="canary-009",
        prompt="Return exactly the result of 5 ** 3 as a single number. No explanation.",
        expected_output="125",
    ),
    CanaryTask(
        canary_id="canary-010",
        prompt="Return exactly the result of 999 + 1 as a single number. No explanation.",
        expected_output="1000",
    ),
    # ── String operations (011-016, stable across model sizes) ───────────────
    CanaryTask(
        canary_id="canary-011",
        prompt="Return exactly the result of 13 * 4 as a single number. No explanation.",
        expected_output="52",
    ),
    CanaryTask(
        canary_id="canary-012",
        prompt="Return exactly the result of 4 ** 2 as a single number. No explanation.",
        expected_output="16",
    ),
    CanaryTask(
        canary_id="canary-013",
        prompt="Return exactly the Python expression result: 'soft-yeti'.replace('-', '_'). No explanation.",
        expected_output="soft_yeti",
    ),
    CanaryTask(
        canary_id="canary-014",
        prompt="Return exactly the Python expression result: ','.join(['x', 'y', 'z']). No explanation.",
        expected_output="x,y,z",
    ),
    CanaryTask(
        canary_id="canary-015",
        prompt="Return exactly the Python expression result: 'nonce'[0]. No explanation.",
        expected_output="n",
    ),
    CanaryTask(
        canary_id="canary-016",
        prompt="Return exactly the Python expression result: 'PROOF'.lower(). No explanation.",
        expected_output="proof",
    ),
    CanaryTask(
        canary_id="canary-017",
        prompt="Return exactly the result of 7 * 7 as a single number. No explanation.",
        expected_output="49",
    ),
    CanaryTask(
        canary_id="canary-018",
        prompt="Return exactly the result of 14 - 7 as a single number. No explanation.",
        expected_output="7",
    ),
    CanaryTask(
        canary_id="canary-019",
        prompt="Return exactly the result of 6 ** 2 + 1 as a single number. No explanation.",
        expected_output="37",
    ),
    CanaryTask(
        canary_id="canary-020",
        prompt="Return exactly the result of 8 * 9 as a single number. No explanation.",
        expected_output="72",
    ),
    # ── Boolean and comparisons (021-030) ─────────────────────────────────────
    CanaryTask(
        canary_id="canary-021",
        prompt="Return exactly the result of 17 + 14 as a single number. No explanation.",
        expected_output="31",
    ),
    CanaryTask(
        canary_id="canary-022",
        prompt="Return exactly the Python expression result: bool(1). No explanation.",
        expected_output="True",
    ),
    CanaryTask(
        canary_id="canary-023",
        prompt="Return exactly the Python expression result: 5 == 5. No explanation.",
        expected_output="True",
    ),
    CanaryTask(
        canary_id="canary-024",
        prompt="Return exactly the result of 9 + 9 as a single number. No explanation.",
        expected_output="18",
    ),
    CanaryTask(
        canary_id="canary-025",
        prompt="Return exactly the Python expression result: 'yeti' in 'soft-yeti'. No explanation.",
        expected_output="True",
    ),
    CanaryTask(
        canary_id="canary-026",
        prompt="Return exactly the Python expression result: 3 != 4. No explanation.",
        expected_output="True",
    ),
    CanaryTask(
        canary_id="canary-027",
        prompt="Return exactly the Python expression result: 5 == 6. No explanation.",
        expected_output="False",
    ),
    CanaryTask(
        canary_id="canary-028",
        prompt="Return exactly the Python expression result: len('yeti') == 4. No explanation.",
        expected_output="True",
    ),
    CanaryTask(
        canary_id="canary-029",
        prompt="Return exactly the result of 11 + 3 as a single number. No explanation.",
        expected_output="14",
    ),
    CanaryTask(
        canary_id="canary-030",
        prompt="Return exactly the Python expression result: 4 != 5. No explanation.",
        expected_output="True",
    ),
    # ── Built-in functions (031-040) ──────────────────────────────────────────
    CanaryTask(
        canary_id="canary-031",
        prompt="Return exactly the result of 88 - 86 as a single number. No explanation.",
        expected_output="2",
    ),
    CanaryTask(
        canary_id="canary-032",
        prompt="Return exactly the Python expression result: max(7, 3, 9, 1). No explanation.",
        expected_output="9",
    ),
    CanaryTask(
        canary_id="canary-033",
        prompt="Return exactly the result of 9 * 11 as a single number. No explanation.",
        expected_output="99",
    ),
    CanaryTask(
        canary_id="canary-034",
        prompt="Return exactly the Python expression result: int(3.9). No explanation.",
        expected_output="3",
    ),
    CanaryTask(
        canary_id="canary-035",
        prompt="Return exactly the Python expression result: str(2 ** 10). No explanation.",
        expected_output="1024",
    ),
    CanaryTask(
        canary_id="canary-036",
        prompt="Return exactly the result of 200 - 199 as a single number. No explanation.",
        expected_output="1",
    ),
    CanaryTask(
        canary_id="canary-037",
        prompt="Return exactly the result of 2 * 2 as a single number. No explanation.",
        expected_output="4",
    ),
    CanaryTask(
        canary_id="canary-038",
        prompt="Return exactly the Python expression result: chr(65). No explanation.",
        expected_output="A",
    ),
    CanaryTask(
        canary_id="canary-039",
        prompt="Return exactly the result of 9 * 10 as a single number. No explanation.",
        expected_output="90",
    ),
    CanaryTask(
        canary_id="canary-040",
        prompt="Return exactly the Python expression result: sum(range(5)). No explanation.",
        expected_output="10",
    ),
    # ── Mixed (041-050) ───────────────────────────────────────────────────────
    CanaryTask(
        canary_id="canary-041",
        prompt="Return exactly the Python expression result: 'Hello World'.split()[1]. No explanation.",
        expected_output="World",
    ),
    CanaryTask(
        canary_id="canary-042",
        prompt="Return exactly the Python expression result: 'mining'.upper(). No explanation.",
        expected_output="MINING",
    ),
    CanaryTask(
        canary_id="canary-043",
        prompt="Return exactly the Python expression result: sum([1, 2, 3, 4, 5]). No explanation.",
        expected_output="15",
    ),
    CanaryTask(
        canary_id="canary-044",
        prompt="Return exactly the result of 3 * 8 as a single number. No explanation.",
        expected_output="24",
    ),
    CanaryTask(
        canary_id="canary-045",
        prompt="Return exactly the result of 2 * 3 as a single number. No explanation.",
        expected_output="6",
    ),
    CanaryTask(
        canary_id="canary-046",
        prompt="Return exactly the Python expression result: [1, 2, 3][-1]. No explanation.",
        expected_output="3",
    ),
    CanaryTask(
        canary_id="canary-047",
        prompt="Return exactly the result of 26 // 2 as a single number. No explanation.",
        expected_output="13",
    ),
    CanaryTask(
        canary_id="canary-048",
        prompt="Return exactly the Python expression result: int('42') + int('8'). No explanation.",
        expected_output="50",
    ),
    CanaryTask(
        canary_id="canary-049",
        prompt="Return exactly the Python expression result: ''.join(sorted('cba')). No explanation.",
        expected_output="abc",
    ),
    CanaryTask(
        canary_id="canary-050",
        prompt="Return exactly the result of 33 // 3 as a single number. No explanation.",
        expected_output="11",
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


_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)
_OUTPUT_SECTION_RE = re.compile(r"[Oo]utput[:\s]*```\s*\n?(.*?)\n?```", re.DOTALL)


def normalize_canary_output(text: str) -> str:
    """Normalize model output before canary comparison.

    Handles the two common formatting variations:
    - Markdown code blocks — extracts Output: section if present, else first line
    - Outer Python string quotes ('value' or "value") — stripped
    """
    text = text.strip()
    # If there is an Output: section inside a code block, that is the result
    out_match = _OUTPUT_SECTION_RE.search(text)
    if out_match:
        return out_match.group(1).strip()
    # If the whole response is a code block, take the first non-empty line
    block_match = _CODE_BLOCK_RE.match(text)
    if block_match:
        first_line = block_match.group(1).strip().split("\n")[0].strip()
        return normalize_canary_output(first_line)
    # Strip outer Python string quotes
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1]
    # Strip trailing punctuation small models sometimes append
    text = text.rstrip(".,!?;:")
    return text


def verify_canary_output(canary: CanaryTask, actual_output: str) -> bool:
    """Validate the canary output, normalizing format before comparison."""
    return normalize_canary_output(actual_output) == canary.expected_output
