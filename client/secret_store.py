"""Windows DPAPI-backed secret storage for the auto-generated wallet passphrase.

Lets the volunteer client encrypt the wallet at rest without ever asking the
user for a passphrase: the passphrase itself is protected by CryptProtectData,
which only the same Windows user account can unprotect (backed by the user's
login credentials -- not a wallet-specific secret the volunteer has to
remember, write down, or lose).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
from pathlib import Path

_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _DataBlob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def protect(data: bytes) -> bytes:
    """Encrypt bytes for the current Windows user via DPAPI."""
    in_blob = _blob(data)
    out_blob = _DataBlob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def unprotect(data: bytes) -> bytes:
    """Decrypt bytes previously protected by `protect()` for this Windows user."""
    in_blob = _blob(data)
    out_blob = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def save_passphrase(path: Path, passphrase: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(protect(passphrase.encode("utf-8")))
    try:
        os.chmod(path, 0o600)
    except (NotImplementedError, AttributeError):
        pass


def load_passphrase(path: Path) -> str | None:
    """Returns None if the file is missing or can't be unprotected (e.g. a
    different Windows user account, or a stale/corrupt file)."""
    if not path.exists():
        return None
    try:
        return unprotect(path.read_bytes()).decode("utf-8")
    except Exception:
        return None
