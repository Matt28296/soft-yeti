"""Encrypted Ed25519 YETI wallet for the volunteer client.

Key derivation: PBKDF2-HMAC-SHA256 (100k iterations) over passphrase + random salt.
Encryption: AES-256-GCM with a random 12-byte nonce per save.
Address format: YETI1 + base58(SHA-256(raw_pubkey_bytes)[:20])

Uses `cryptography` package only — do NOT mix in PyNaCl (serialization incompatibility).
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

_BASE58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58encode(data: bytes) -> str:
    leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    n = int.from_bytes(data, "big")
    chars: list[bytes] = []
    while n:
        n, r = divmod(n, 58)
        chars.append(_BASE58_ALPHABET[r : r + 1])
    return "1" * leading_zeros + b"".join(reversed(chars)).decode("ascii")


def _pubkey_bytes(pubkey: Ed25519PublicKey) -> bytes:
    return pubkey.public_bytes(Encoding.Raw, PublicFormat.Raw)


def address_from_pubkey(pubkey: Ed25519PublicKey) -> str:
    """Derive the YETI1... wallet address from a public key."""
    digest = hashlib.sha256(_pubkey_bytes(pubkey)).digest()[:20]
    return "YETI1" + _b58encode(digest)


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100_000)
    return kdf.derive(passphrase.encode("utf-8"))


def generate_wallet() -> dict[str, str]:
    """Generate a fresh Ed25519 YETI wallet.

    Returns dict with keys: address, pubkey_hex, privkey_hex.
    privkey_hex is the raw 32-byte private key in hex — keep it secret.
    """
    privkey = Ed25519PrivateKey.generate()
    pubkey = privkey.public_key()
    return {
        "address": address_from_pubkey(pubkey),
        "pubkey_hex": _pubkey_bytes(pubkey).hex(),
        "privkey_hex": privkey.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex(),
    }


def save_wallet(wallet: dict[str, str], path: Path, passphrase: str = "") -> None:
    """Persist the wallet to disk, optionally AES-256-GCM encrypted.

    When passphrase is empty the wallet is stored unencrypted (Phase 0 only).
    Phase 2+ always passes a non-empty passphrase.
    """
    plaintext = json.dumps(wallet).encode("utf-8")
    payload: dict[str, Any]
    if passphrase:
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)
        key = _derive_key(passphrase, salt)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
        payload = {
            "encrypted": True,
            "salt": salt.hex(),
            "nonce": nonce.hex(),
            "ciphertext": ciphertext.hex(),
        }
    else:
        payload = {"encrypted": False, "data": wallet}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except (NotImplementedError, AttributeError):
        pass  # Windows — ACL management is the caller's responsibility if needed


def sign_message(privkey_hex: str, message: bytes) -> str:
    """Sign arbitrary bytes with the wallet's Ed25519 private key. Returns hex signature."""
    privkey = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(privkey_hex))
    return privkey.sign(message).hex()


def load_wallet(path: Path, passphrase: str = "") -> dict[str, str]:
    """Load and decrypt a wallet from disk."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("encrypted"):
        return dict(payload["data"])
    salt = bytes.fromhex(payload["salt"])
    nonce = bytes.fromhex(payload["nonce"])
    ciphertext = bytes.fromhex(payload["ciphertext"])
    key = _derive_key(passphrase, salt)
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    return json.loads(plaintext.decode("utf-8"))
