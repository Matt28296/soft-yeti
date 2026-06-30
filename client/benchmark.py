"""GPU micro-benchmark for Theory 7 inference timing correlation.

Phase 0/1: numpy matrix multiply — CPU timing baseline. The signature encodes
shape + elapsed time + a result digest so the coordinator can detect gross faking.

Phase 2 upgrade path: replace _run_numpy with a PyOpenCL or Vulkan compute kernel
so the timing is tied to actual GPU VRAM bandwidth, not CPU.
"""
from __future__ import annotations

import hashlib
import time


def _run_numpy(size: int, rounds: int) -> tuple[float, str]:
    """Matrix multiply benchmark. Returns (elapsed_seconds, result_digest)."""
    import numpy as np

    acc_bytes = b""
    t0 = time.perf_counter()
    for _ in range(rounds):
        a = np.random.rand(size, size).astype(np.float32)
        b = np.random.rand(size, size).astype(np.float32)
        c = np.dot(a, b)
        acc_bytes += c.tobytes()[:64]
    elapsed = time.perf_counter() - t0
    digest = hashlib.sha256(acc_bytes).hexdigest()[:16]
    return elapsed, digest


def _run_fallback(size: int, rounds: int) -> tuple[float, str]:
    """Pure-Python fallback when numpy is unavailable."""
    t0 = time.perf_counter()
    acc = 0
    for i in range(size * rounds):
        acc ^= (i * 0x9E3779B9) & 0xFFFFFFFF
    elapsed = time.perf_counter() - t0
    digest = hashlib.sha256(acc.to_bytes(4, "big")).hexdigest()[:16]
    return elapsed, digest


def run_benchmark(size: int = 512, rounds: int = 3) -> tuple[str, float]:
    """Run the micro-benchmark and return (benchmark_signature, elapsed_seconds).

    The signature is an opaque string the coordinator stores alongside the block.
    It encodes enough information to detect cases where no computation occurred.
    """
    try:
        elapsed, digest = _run_numpy(size, rounds)
        backend = "np"
    except ImportError:
        elapsed, digest = _run_fallback(size, rounds)
        backend = "cpu"

    elapsed_ms = int(elapsed * 1000)
    signature = f"{backend}-{size}x{size}x{rounds}-{elapsed_ms}ms-{digest}"
    return signature, elapsed
