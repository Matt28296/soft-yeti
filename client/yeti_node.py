"""Soft Yeti volunteer node — heartbeat loop + Proof-of-Inference nonce search.

Flow per task:
  1. Poll GET /api/task/next (authenticated) to receive a TaskAssignment.
  2. Run GPU micro-benchmark concurrently (Theory 7 timing signature).
  3. Run Ollama inference at temperature > 0 (temperature from assignment).
  4. Compute SHA-256(output_text + task_id + task_salt).
  5. If hash meets difficulty_target → submit via POST /api/submit.
  6. If not → repeat from step 3 (next nonce attempt).
  7. On canary tasks the coordinator checks output against known-exact answers.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any

import requests

from benchmark import run_benchmark
from yeti_config import YetiConfig

logger = logging.getLogger(__name__)

_STOP_EVENT = threading.Event()


# ── Hash helpers ──────────────────────────────────────────────────────────────

def _output_hash(output_text: str, task_id: str, task_salt: str) -> str:
    return hashlib.sha256(
        f"{output_text}{task_id}{task_salt}".encode("utf-8")
    ).hexdigest()


def _meets_difficulty(output_hash: str, difficulty_target: str) -> bool:
    if not difficulty_target:
        return True
    return output_hash.startswith(difficulty_target)


# ── Ollama inference ──────────────────────────────────────────────────────────

def _run_inference(
    ollama_host: str,
    model: str,
    system: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
) -> tuple[str, int, int]:
    """One inference attempt via the local Ollama instance.

    Returns (output_text, prompt_tokens, completion_tokens).
    Raises on connection failure or model-not-found.
    """
    import ollama  # imported here so the module loads even without ollama installed

    client = ollama.Client(host=ollama_host, timeout=300)
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = client.chat(
        model=model,
        messages=messages,
        options={
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": 4096,
        },
    )
    content = resp.message.content or ""
    prompt_tokens = int(getattr(resp, "prompt_eval_count", None) or 0)
    completion_tokens = int(getattr(resp, "eval_count", None) or 0)
    return content.strip(), prompt_tokens, completion_tokens


# ── PoI nonce search ──────────────────────────────────────────────────────────

def _nonce_search(
    cfg: YetiConfig,
    assignment: dict[str, Any],
    bench_sig: str,
    wallet_address: str,
) -> bool:
    """Run the PoI nonce search for one assignment.

    Iterates inference until the output hash meets the difficulty target, then
    submits the result to the coordinator. Returns True on accepted submission.
    """
    task_id = assignment["task_id"]
    task_salt = assignment["task_salt"]
    difficulty_target = assignment.get("difficulty_target", "")
    system = assignment.get("system", "")
    prompt = assignment.get("prompt", "")
    temperature = float(assignment.get("temperature", 0.3))
    max_tokens = int(assignment.get("max_tokens", 512))

    nonce_attempts = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0

    while not _STOP_EVENT.is_set():
        nonce_attempts += 1
        try:
            output_text, pt, ct = _run_inference(
                cfg.ollama_host, cfg.model_name, system, prompt, temperature, max_tokens,
            )
        except Exception as exc:
            logger.warning("Inference attempt %d failed for task %s: %s", nonce_attempts, task_id, exc)
            return False

        total_prompt_tokens += pt
        total_completion_tokens += ct
        oh = _output_hash(output_text, task_id, task_salt)

        if _meets_difficulty(oh, difficulty_target):
            payload = {
                "task_id": task_id,
                "volunteer_id": cfg.volunteer_id,
                "miner_wallet": wallet_address,
                "output_text": output_text,
                "output_hash": oh,
                "nonce_attempts": nonce_attempts,
                "benchmark_signature": bench_sig,
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "task_salt": task_salt,
            }
            try:
                resp = requests.post(
                    f"{cfg.coordinator_url}/api/submit",
                    json=payload,
                    headers={"X-Yeti-API-Key": f"{cfg.volunteer_id}:{cfg.api_key}"},
                    timeout=30,
                )
                resp.raise_for_status()
                result = resp.json()
                if result.get("accepted"):
                    logger.info(
                        "Block minted — task=%s attempts=%d reward=%s",
                        task_id, nonce_attempts, result.get("miner_reward"),
                    )
                    return True
                logger.warning("Submission rejected: %s", result.get("reason"))
                return False
            except Exception as exc:
                logger.error("Submit error for task %s: %s", task_id, exc)
                return False

        if nonce_attempts >= cfg.max_nonce_attempts:
            logger.warning("Max nonce attempts (%d) reached for task %s", cfg.max_nonce_attempts, task_id)
            return False

    return False


# ── Background loops ──────────────────────────────────────────────────────────

def heartbeat_loop(cfg: YetiConfig) -> None:
    """POST /api/heartbeat on a fixed interval to keep the volunteer lease alive."""
    headers = {"X-Yeti-API-Key": f"{cfg.volunteer_id}:{cfg.api_key}"}
    while not _STOP_EVENT.is_set():
        try:
            requests.post(
                f"{cfg.coordinator_url}/api/heartbeat",
                headers=headers,
                timeout=10,
            )
        except Exception as exc:
            logger.debug("Heartbeat failed: %s", exc)
        _STOP_EVENT.wait(cfg.heartbeat_interval_s)


def inference_loop(cfg: YetiConfig, wallet_address: str) -> None:
    """Poll for tasks and run the PoI nonce search loop."""
    headers = {"X-Yeti-API-Key": f"{cfg.volunteer_id}:{cfg.api_key}"}
    logger.info("Inference loop started (volunteer=%s model=%s)", cfg.volunteer_id, cfg.model_name)

    while not _STOP_EVENT.is_set():
        try:
            bench_sig, _ = run_benchmark()

            resp = requests.get(
                f"{cfg.coordinator_url}/api/task/next",
                headers=headers,
                timeout=30,
            )
            if resp.status_code == 404:
                _STOP_EVENT.wait(cfg.task_poll_interval_s)
                continue
            resp.raise_for_status()
            assignment = resp.json()
            logger.info("Task received: %s", assignment.get("task_id"))
            _nonce_search(cfg, assignment, bench_sig, wallet_address)

        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (401, 403):
                logger.error("Auth rejected — check volunteer_id / api_key in config")
                _STOP_EVENT.set()
                return
            logger.warning("HTTP error in inference loop: %s", exc)
            _STOP_EVENT.wait(5.0)
        except Exception as exc:
            logger.warning("Inference loop error: %s", exc)
            _STOP_EVENT.wait(5.0)


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def start(cfg: YetiConfig, wallet_address: str) -> None:
    """Start heartbeat and inference threads (both daemon threads)."""
    _STOP_EVENT.clear()
    threading.Thread(
        target=heartbeat_loop, args=(cfg,), daemon=True, name="yeti-heartbeat",
    ).start()
    threading.Thread(
        target=inference_loop, args=(cfg, wallet_address), daemon=True, name="yeti-inference",
    ).start()


def stop() -> None:
    """Signal both background threads to exit cleanly."""
    _STOP_EVENT.set()


def is_running() -> bool:
    return not _STOP_EVENT.is_set()
