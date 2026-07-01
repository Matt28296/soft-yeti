"""Soft Yeti volunteer client entry point.

Phase 0/1: CLI mode. Registers with the coordinator, then runs the heartbeat +
inference loops until interrupted. Tray icon (pystray) is optional — falls back
to CLI when pystray / Pillow are not installed.

Usage:
    python yeti_client.py [--setup]   # --setup scans hardware + generates wallet, no prompts
    python yeti_client.py             # start mining with existing config
"""
from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import secrets
import sys
import time
from pathlib import Path

import requests

import secret_store
from chain_client import ChainClient
from yeti_config import DEFAULT_CONFIG_PATH, YetiConfig
from yeti_node import start as node_start, stop as node_stop
from yeti_wallet import generate_wallet, load_wallet, save_wallet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_COORDINATOR_URL = "https://api.soft-yeti.com"
WALLET_KEY_PATH = Path.home() / ".soft_yeti" / "wallet.key"


# ── Setup wizard ──────────────────────────────────────────────────────────────

def _setup(cfg_path: Path) -> None:
    """Non-interactive first-run setup: no prompts, ever.

    setup_volunteer.ps1 scans the machine (GPU/VRAM) and passes the result in
    via env vars; this just consumes them, generates or reuses a wallet, and
    registers with the coordinator. The volunteer's only interaction with the
    product is the dashboard on/off toggle.

    Re-running this (e.g. after a coordinator restart, or a re-run of
    setup.bat to pick up a fix) reuses the existing wallet + volunteer_id
    instead of silently orphaning them — only a fresh identity is generated
    the very first time.
    """
    print("\n=== Soft Yeti Setup (automatic) ===\n")

    coordinator_url = os.environ.get("YETI_COORDINATOR_URL", DEFAULT_COORDINATOR_URL).strip() or DEFAULT_COORDINATOR_URL
    default_model = os.environ.get("YETI_DETECTED_MODEL", "qwen2.5-coder:7b-instruct")
    default_vram  = os.environ.get("YETI_DETECTED_VRAM", "8.0")
    detected_gpu  = os.environ.get("YETI_DETECTED_GPU", "")

    model_name = default_model
    try:
        vram_gb = float(default_vram)
    except ValueError:
        vram_gb = 8.0

    wallet_path = Path.home() / ".soft_yeti" / "wallet.json"
    existing_cfg = YetiConfig.load(cfg_path) if cfg_path.exists() else None

    if existing_cfg and existing_cfg.volunteer_id and wallet_path.exists():
        print("Existing wallet + volunteer identity found — reusing them, refreshing registration.")
        try:
            passphrase = secret_store.load_passphrase(WALLET_KEY_PATH) or ""
            wallet = load_wallet(wallet_path, passphrase=passphrase)
        except Exception as exc:
            print(f"[error] Could not unlock existing wallet ({exc}). Move or delete {wallet_path} to start fresh.")
            sys.exit(1)
        volunteer_id = existing_cfg.volunteer_id
    else:
        print(f"Generating Ed25519 wallet -> {wallet_path}")
        passphrase = secrets.token_urlsafe(32)
        wallet = generate_wallet()
        save_wallet(wallet, wallet_path, passphrase=passphrase)
        secret_store.save_passphrase(WALLET_KEY_PATH, passphrase)
        print("Wallet encrypted at rest; the key is protected for your Windows account only —")
        print("there's no passphrase to remember or type.")
        volunteer_id = f"volunteer-{secrets.token_hex(6)}"

    print(f"Wallet address: {wallet['address']}")
    print(f"\nRegistering volunteer {volunteer_id} with {coordinator_url} ...")
    try:
        resp = requests.post(
            f"{coordinator_url.rstrip('/')}/api/register",
            json={
                "volunteer_id": volunteer_id,
                "miner_wallet": wallet["address"],
                "miner_pubkey": wallet["pubkey_hex"],
                "model_name": model_name,
                "vram_gb": vram_gb,
            },
            timeout=10,
        )
        resp.raise_for_status()
        api_key = resp.json()["api_key"]
        print("Registration successful.")
    except Exception as exc:
        print(f"Registration failed: {exc}")
        print("Saving config without a fresh API key — will retry automatically once the coordinator is reachable.")
        api_key = existing_cfg.api_key if existing_cfg else ""

    cfg = YetiConfig(
        coordinator_url=coordinator_url,
        volunteer_id=volunteer_id,
        model_name=model_name,
        vram_gb=vram_gb,
        gpu_name=detected_gpu,
        wallet_path=str(wallet_path),
        api_key=api_key,
        enabled=True,
    )
    cfg.save(cfg_path)
    print(f"\nConfig saved to {cfg_path}")
    print("Setup complete — open the dashboard and use the toggle to start mining.\n")


# ── Tray icon (optional) ──────────────────────────────────────────────────────

def _run_tray(cfg: YetiConfig, wallet_address: str, miner_pubkey: str, privkey_hex: str) -> None:
    """Run with a system tray icon when pystray + Pillow are available."""
    import pystray
    from PIL import Image, ImageDraw

    def _icon_image(color: str) -> Image.Image:
        img = Image.new("RGB", (64, 64), color=(30, 30, 30))
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 56, 56], fill=color)
        return img

    chain = ChainClient(cfg.coordinator_url)

    def _balance_action(icon, item) -> None:  # noqa: ARG001
        try:
            bal = chain.get_balance(wallet_address)
            icon.notify(f"Balance: {bal:.4f} YETI", title="Soft Yeti")
        except Exception as exc:
            icon.notify(f"Error: {exc}", title="Soft Yeti")

    def _toggle_action(icon, item) -> None:  # noqa: ARG001
        if yeti_node.is_running():
            node_stop()
            icon.icon = _icon_image("#888888")
            icon.title = "Soft Yeti — Stopped"
        else:
            node_start(cfg, wallet_address, miner_pubkey, privkey_hex)
            icon.icon = _icon_image("#00cc44")
            icon.title = "Soft Yeti — Mining"

    def _quit_action(icon, item) -> None:  # noqa: ARG001
        node_stop()
        icon.stop()

    import yeti_node
    node_start(cfg, wallet_address, miner_pubkey, privkey_hex)

    icon = pystray.Icon(
        "soft_yeti",
        _icon_image("#00cc44"),
        title="Soft Yeti — Mining",
        menu=pystray.Menu(
            pystray.MenuItem("Check balance", _balance_action),
            pystray.MenuItem("Toggle mining", _toggle_action),
            pystray.MenuItem("Quit", _quit_action),
        ),
    )
    icon.run()


# ── CLI mode ──────────────────────────────────────────────────────────────────

def _run_cli(cfg: YetiConfig, wallet_address: str, miner_pubkey: str, privkey_hex: str) -> None:
    """CLI fallback — runs mining loops and blocks until Ctrl-C."""
    logger.info("Starting Soft Yeti (CLI mode)  volunteer=%s  wallet=%s", cfg.volunteer_id, wallet_address)
    node_start(cfg, wallet_address, miner_pubkey, privkey_hex)
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Interrupted — shutting down.")
        node_stop()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Soft Yeti volunteer client")
    parser.add_argument("--setup", action="store_true", help="Run first-time setup wizard")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Config file path")
    args = parser.parse_args()

    cfg_path = Path(args.config)

    if args.setup:
        _setup(cfg_path)
        return

    cfg = YetiConfig.load(cfg_path)
    if not cfg.volunteer_id or not cfg.api_key:
        print("No config found. Run:  python yeti_client.py --setup")
        sys.exit(1)

    wallet_path = Path(cfg.wallet_path)
    if not wallet_path.exists():
        print(f"Wallet not found at {wallet_path}. Run:  python yeti_client.py --setup")
        sys.exit(1)

    raw_payload = json.loads(wallet_path.read_text(encoding="utf-8"))
    if raw_payload.get("encrypted"):
        wallet_passphrase = secret_store.load_passphrase(WALLET_KEY_PATH)
        if wallet_passphrase is None:
            if sys.stdin.isatty():
                wallet_passphrase = getpass.getpass("Wallet passphrase: ")
            else:
                # Launched headlessly (e.g. by the dashboard toggle) with no
                # stored key and no attached terminal -- fail fast instead of
                # hanging forever on a prompt nobody can answer.
                print(f"Encrypted wallet found but no stored key at {WALLET_KEY_PATH} and no "
                      f"terminal to prompt in. Run:  python yeti_client.py --setup")
                sys.exit(1)
    else:
        wallet_passphrase = ""
    wallet = load_wallet(wallet_path, passphrase=wallet_passphrase)
    wallet_address = wallet["address"]
    miner_pubkey = wallet["pubkey_hex"]
    privkey_hex = wallet["privkey_hex"]

    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
        _run_tray(cfg, wallet_address, miner_pubkey, privkey_hex)
    except ImportError:
        _run_cli(cfg, wallet_address, miner_pubkey, privkey_hex)


if __name__ == "__main__":
    main()
