"""
Coordinator-side block signing and any-node signature verification.

The coordinator holds the sole signing key (Phase 1). It signs blocks after
verifying the PoI nonce and all other verification layers. Any participant
can verify the signature with the coordinator's public key.

Uses `cryptography` package only throughout — do not mix PyNaCl.
Signing key must be stored encrypted (AES-256-GCM) outside this module;
this module only handles the Ed25519 sign/verify operations.
"""

from cryptography.exceptions import InvalidSignature
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

from .block import Block


def sign_block(block: Block, coordinator_privkey_hex: str) -> Block:
    """
    Sign a block with the coordinator's Ed25519 private key.

    Sets block.coordinator_signature, then calls block.finalize() to set
    block.block_hash over all fields including the signature.
    Returns the same block object (mutated in place).

    block.coordinator_signature must be "" before calling this.
    """
    privkey = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(coordinator_privkey_hex)
    )
    # Sign over signing_payload() — excludes coordinator_signature and block_hash.
    # block_hash is set by finalize() after the signature is placed.
    payload = block.signing_payload()
    block.coordinator_signature = privkey.sign(payload).hex()
    block.finalize()
    return block


def verify_block_signature(block: Block, coordinator_pubkey_hex: str) -> bool:
    """
    Verify a block's coordinator_signature.

    Reconstructs the payload that was signed (canonical_bytes() with
    coordinator_signature present but block_hash absent), then verifies.
    Returns True if valid.
    """
    pubkey = Ed25519PublicKey.from_public_bytes(
        bytes.fromhex(coordinator_pubkey_hex)
    )
    # Reconstruct the payload that was signed: signing_payload() excludes
    # coordinator_signature and block_hash, matching what sign_block() signed over.
    payload = block.signing_payload()
    try:
        pubkey.verify(bytes.fromhex(block.coordinator_signature), payload)
        return True
    except InvalidSignature:
        return False


def verify_block_hash(block: Block) -> bool:
    """Verify block.block_hash matches a fresh computation of canonical_bytes()."""
    return block.block_hash == block.compute_hash()


def coordinator_pubkey_hex(coordinator_privkey_hex: str) -> str:
    """Derive the hex public key from a hex private key (for key setup / display)."""
    privkey = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(coordinator_privkey_hex)
    )
    return privkey.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
