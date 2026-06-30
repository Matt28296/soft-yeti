"""
YETI wallet — Ed25519 key pair, YETI1... address format, signing.

Address derivation: YETI1 + base58(SHA-256(compressed_pubkey_bytes)[:20])
Uses `cryptography` package only — do NOT mix in PyNaCl (serialization incompatibility).
"""

import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

_BASE58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58encode(data: bytes) -> str:
    count = 0
    for b in data:
        if b == 0:
            count += 1
        else:
            break
    n = int.from_bytes(data, "big")
    chars = []
    while n:
        n, r = divmod(n, 58)
        chars.append(_BASE58_ALPHABET[r : r + 1])
    return ("1" * count + b"".join(reversed(chars)).decode("ascii"))


def _b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + _BASE58_ALPHABET.index(c.encode())
    result = n.to_bytes((n.bit_length() + 7) // 8 or 1, "big")
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + result


def _pubkey_bytes(pubkey: Ed25519PublicKey) -> bytes:
    return pubkey.public_bytes(Encoding.Raw, PublicFormat.Raw)


def _privkey_bytes(privkey: Ed25519PrivateKey) -> bytes:
    return privkey.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())


def address_from_pubkey(pubkey: Ed25519PublicKey) -> str:
    """Derive YETI1... wallet address from a public key."""
    digest = hashlib.sha256(_pubkey_bytes(pubkey)).digest()[:20]
    return "YETI1" + _b58encode(digest)


def generate_wallet() -> dict:
    """
    Generate a new YETI wallet.

    Returns a dict with:
        address  — YETI1... string
        pubkey   — hex-encoded raw public key (32 bytes)
        privkey  — hex-encoded raw private key (32 bytes) — KEEP SECRET
    """
    privkey = Ed25519PrivateKey.generate()
    pubkey = privkey.public_key()
    return {
        "address": address_from_pubkey(pubkey),
        "pubkey": _pubkey_bytes(pubkey).hex(),
        "privkey": _privkey_bytes(privkey).hex(),
    }


def load_wallet(path: str | Path) -> dict:
    """Load wallet JSON from disk. Returns dict with address/pubkey/privkey."""
    with open(path, "r") as f:
        return json.load(f)


def save_wallet(wallet: dict, path: str | Path) -> None:
    """Save wallet to disk (600 permissions — owner read/write only on POSIX)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(wallet, f, indent=2)
    try:
        os.chmod(path, 0o600)
    except NotImplementedError:
        pass  # Windows — caller is responsible for ACL if needed


def sign_message(privkey_hex: str, message: bytes) -> str:
    """Sign arbitrary bytes with the wallet's private key. Returns hex signature."""
    privkey_bytes = bytes.fromhex(privkey_hex)
    privkey = Ed25519PrivateKey.from_private_bytes(privkey_bytes)
    return privkey.sign(message).hex()


def verify_signature(pubkey_hex: str, message: bytes, signature_hex: str) -> bool:
    """Verify a hex-encoded Ed25519 signature against a public key."""
    from cryptography.exceptions import InvalidSignature

    pubkey_bytes = bytes.fromhex(pubkey_hex)
    pubkey = Ed25519PublicKey.from_public_bytes(pubkey_bytes)
    try:
        pubkey.verify(bytes.fromhex(signature_hex), message)
        return True
    except InvalidSignature:
        return False


def validate_address(address: str) -> bool:
    """Return True if address looks like a valid YETI1... wallet address."""
    if not address.startswith("YETI1"):
        return False
    suffix = address[5:]
    if len(suffix) < 10:
        return False
    try:
        _b58decode(suffix)
        return True
    except (ValueError, KeyError):
        return False
