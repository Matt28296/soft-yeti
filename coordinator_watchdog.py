#!/usr/bin/env python3
"""
coordinator_watchdog.py -- Soft Yeti auto-failover watchdog (3060 Ti)

Monitors the primary coordinator and auto-starts/stops the secondary.

Activation conditions (BOTH required):
  1. Both TAILSCALE_HEALTH and PUBLIC_HEALTH fail for >= FAIL_THRESHOLD consecutive polls (90s)
  2. yeti-chain.jsonl mtime > CHAIN_STALE_SEC ago (primary truly down, not just a Tailscale partition)

Deactivation: either health endpoint responds OK -> stop secondary immediately.
"""
import os
import shutil
import subprocess
import sys
import time
import logging
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────
TAILSCALE_HEALTH = "http://100.92.46.126:8900/api/health"
PUBLIC_HEALTH    = "https://api.soft-yeti.com/api/health"

SYNC_DIR         = Path(os.environ.get("USERPROFILE", r"C:\Users\Matthew")) / "yetiSync"
CHAIN_FILE       = SYNC_DIR / "yeti-chain.jsonl"

POLL_SEC         = 30    # seconds between polls
FAIL_THRESHOLD   = 3     # consecutive dual-check failures before activating (= 90s)
CHAIN_STALE_SEC  = 600   # 10 min -- > 1 missed Syncthing cycle confirms primary down

SCRIPT_DIR       = Path(__file__).parent
SECONDARY_SCRIPT = SCRIPT_DIR / "start_coordinator_secondary.ps1"
COORD_ENV        = SCRIPT_DIR / "coordinator" / ".env"
COORD_ENV_BAK    = SCRIPT_DIR / "coordinator" / ".env.primary.bak"
LOG_FILE         = SCRIPT_DIR / "watchdog.log"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def check_health(url):
    try:
        r = requests.get(url, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def chain_age_secs():
    """Seconds since yeti-chain.jsonl was last written. Returns inf if file missing."""
    if not CHAIN_FILE.exists():
        return float("inf")
    return time.time() - CHAIN_FILE.stat().st_mtime


def restore_env():
    """Restore primary .env if secondary didn't clean up after itself."""
    if COORD_ENV_BAK.exists():
        shutil.copy2(COORD_ENV_BAK, COORD_ENV)
        log.info("Restored coordinator/.env from .env.primary.bak")


def start_secondary():
    log.info("ACTIVATING secondary coordinator")
    proc = subprocess.Popen(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File",
         str(SECONDARY_SCRIPT), "-SyncDir", str(SYNC_DIR)],
    )
    log.info("Secondary started (PID %d)", proc.pid)
    return proc


def stop_secondary(proc):
    if proc.poll() is not None:
        log.info("Secondary already exited (code %s)", proc.returncode)
        restore_env()
        return
    log.info("DEACTIVATING secondary coordinator (PID %d)", proc.pid)
    proc.terminate()
    try:
        proc.wait(timeout=15)
        log.info("Secondary exited cleanly.")
    except subprocess.TimeoutExpired:
        log.warning("Secondary didn't exit in 15s -- killing.")
        proc.kill()
        proc.wait()
    restore_env()


def main():
    log.info(
        "Watchdog started -- poll=%ds  threshold=%d  chain_stale=%ds",
        POLL_SEC, FAIL_THRESHOLD, CHAIN_STALE_SEC,
    )
    log.info("Tailscale health: %s", TAILSCALE_HEALTH)
    log.info("Public health:    %s", PUBLIC_HEALTH)
    log.info("Chain file:       %s", CHAIN_FILE)

    failures = 0
    secondary = None

    try:
        while True:
            # Detect secondary that crashed on its own
            if secondary is not None and secondary.poll() is not None:
                log.warning("Secondary exited unexpectedly (code %s) -- cleared.",
                            secondary.returncode)
                restore_env()
                secondary = None

            # Health checks -- both must fail simultaneously to count
            tail_ok   = check_health(TAILSCALE_HEALTH)
            pub_ok    = check_health(PUBLIC_HEALTH)
            both_down = not tail_ok and not pub_ok

            if both_down:
                failures += 1
                log.info("Health FAIL %d/%d -- tailscale=%s public=%s",
                         failures, FAIL_THRESHOLD, tail_ok, pub_ok)
            else:
                if failures:
                    log.info("Health OK -- resetting failure counter (was %d)", failures)
                failures = 0
                if secondary is not None:
                    stop_secondary(secondary)
                    secondary = None
                    log.info("Primary restored -- secondary deactivated.")

            # Activation: threshold met + fencing check
            if failures >= FAIL_THRESHOLD and secondary is None:
                age = chain_age_secs()
                if age > CHAIN_STALE_SEC:
                    log.info(
                        "Fencing PASSED -- chain age=%.0fs > %ds -- starting secondary",
                        age, CHAIN_STALE_SEC,
                    )
                    secondary = start_secondary()
                else:
                    log.info(
                        "Fencing BLOCKED -- chain age=%.0fs (primary may be alive via other path)",
                        age,
                    )

            time.sleep(POLL_SEC)

    except KeyboardInterrupt:
        log.info("Watchdog stopped by user.")
        if secondary is not None:
            stop_secondary(secondary)


if __name__ == "__main__":
    main()
