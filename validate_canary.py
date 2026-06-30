"""Empirical canary validation.

Run all 50 canary prompts through a local Ollama model at temperature=0 and
verify that each output exactly matches the expected value (after stripping).

Usage (from soft-yeti/ directory):
    python validate_canary.py
    python validate_canary.py --model llama3:8b
    python validate_canary.py --model qwen2.5-coder:7b-instruct --host http://localhost:11434

The script prints PASS/FAIL for each task and a summary at the end.
Any FAIL means that canary task's expected output is wrong for this model —
update coordinator/canary.py if the model can't be changed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

# Allow importing from the coordinator package
sys.path.insert(0, str(Path(__file__).parent))

from coordinator.canary import CANARY_TASKS


def _run_inference(host: str, model: str, prompt: str) -> str:
    """Call Ollama /api/generate at temperature=0 and return the response text."""
    resp = requests.post(
        f"{host.rstrip('/')}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "seed": 42},
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate canary tasks against a local Ollama model")
    parser.add_argument("--model", default="qwen2.5-coder:7b-instruct", help="Ollama model to test")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama host URL")
    args = parser.parse_args()

    print(f"\nValidating {len(CANARY_TASKS)} canary tasks against {args.model} @ {args.host}\n")
    print(f"{'ID':<15} {'Expected':<20} {'Got':<40} {'Result'}")
    print("-" * 95)

    passed = 0
    failed = 0
    errors = 0
    failures: list[tuple[str, str, str]] = []

    for task in CANARY_TASKS:
        try:
            raw_output = _run_inference(args.host, args.model, task.prompt)
            actual = raw_output.strip()
            expected = task.expected_output.strip()
            ok = actual == expected
            if ok:
                passed += 1
                status = "PASS"
            else:
                failed += 1
                status = "FAIL"
                failures.append((task.canary_id, expected, actual))
            print(f"{task.canary_id:<15} {expected:<20} {actual[:38]:<40} {status}")
        except Exception as exc:
            errors += 1
            print(f"{task.canary_id:<15} {'?':<20} {'ERROR: ' + str(exc)[:32]:<40} ERROR")

    print("-" * 95)
    print(f"\nResults: {passed} passed / {failed} failed / {errors} errors  (total {len(CANARY_TASKS)})\n")

    if failures:
        print("FAILURES — update coordinator/canary.py expected outputs for this model:")
        for canary_id, expected, actual in failures:
            print(f"  {canary_id}: expected {expected!r}  got {actual!r}")
        print()

    if failed or errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
