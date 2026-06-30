"""Soft Yeti volunteer client entry point.

Phase 0/1: CLI mode. Registers with the coordinator, then runs the heartbeat +
inference loops until interrupted. Tray icon (pystray) is optional — falls back
to CLI when pystray / Pillow are not installed.

Usage:
    python yeti_client.py [--setup]   # --setup generates wallet + config interactively
    python yeti_client.py             # start mining with existing config
"""
from __future__ import annotations

import argparse
import logging
import secrets
import sys
import time
from pathlib import Path

import requests

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


# ── Setup wizard ──────────────────────────────────────────────────────────────

def _setup(cfg_path: Path) -> None:
    """Interactive first-run setup: generate wallet, register volunteer, save config."""
    print("\n=== Soft Yeti Setup ===\n")
    coordinator_url = input("Coordinator URL [http://localhost:8000]: ").strip() or "http://localhost:8000"
    model_name = input("Ollama model name [qwen2.5-coder:7b-instruct]: ").strip() or "qwen2.5-coder:7b-instruct"
    try:
        vram_gb_str = input("GPU VRAM in GB [8.0]: ").strip() or "8.0"
        vram_gb = float(vram_gb_str)
    except ValueError:
        vram_gb = 8.0

    wallet_path = Path.home() / ".soft_yeti" / "wallet.json"
    print(f"\nGenerating Ed25519 wallet → {wallet_path}")
    wallet = generate_wallet()
    save_wallet(wallet, wallet_path)
    print(f"Wallet address: {wallet['address']}")

    volunteer_id = f"volunteer-{secrets.token_hex(6)}"
    print(f"\nRegistering volunteer {volunteer_id} with coordinator...")
    try:
        resp = requests.post(
            f"{coordinator_url.rstrip('/')}/api/register",
            json={
                "volunteer_id": volunteer_id,
                "miner_wallet": wallet["address"],
                "model_name": model_name,
                "vram_gb": vram_gb,
            },
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        api_key = payload["api_key"]
        print("Registration successful.")
    except Exception as exc:
        print(f"Registration failed: {exc}")
        print("Saving config without API key — re-run setup once coordinator is reachable.")
        api_key = ""

    cfg = YetiConfig(
        coordinator_url=coordinator_url,
        volunteer_id=volunteer_id,
        model_name=model_name,
        vram_gb=vram_gb,
        wallet_path=str(wallet_path),
        api_key=api_key,
        enabled=True,
    )
    cfg.save(cfg_path)
    print(f"\nConfig saved to {cfg_path}")
    print("Run  python yeti_client.py  to start mining.\n")


# ── Tray icon (optional) ──────────────────────────────────────────────────────

def _run_tray(cfg: YetiConfig, wallet_address: str) -> None:
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
            node_start(cfg, wallet_address)
            icon.icon = _icon_image("#00cc44")
            icon.title = "Soft Yeti — Mining"

    def _quit_action(icon, item) -> None:  # noqa: ARG001
        node_stop()
        icon.stop()

    import yeti_node
    node_start(cfg, wallet_address)

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

def _run_cli(cfg: YetiConfig, wallet_address: str) -> None:
    """CLI fallback — runs mining loops and blocks until Ctrl-C."""
    logger.info("Starting Soft Yeti (CLI mode)  volunteer=%s  wallet=%s", cfg.volunteer_id, wallet_address)
    node_start(cfg, wallet_address)
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

    wallet = load_wallet(wallet_path)
    wallet_address = wallet["address"]

    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
        _run_tray(cfg, wallet_address)
    except ImportError:
        _run_cli(cfg, wallet_address)


if __name__ == "__main__":
    main()
