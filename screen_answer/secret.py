"""Windows DPAPI helpers so the API key is not stored in plain text."""

from __future__ import annotations

import base64
import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger(__name__)

PREFIX = "dpapi:"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _crypt(protect: bool, data: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    fn.restype = wintypes.BOOL

    blob_in, _buf_in = _blob(data)
    blob_out = _DataBlob()
    # UI_FORBIDDEN = 1: never show a system prompt.
    ok = fn(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        1,
        ctypes.byref(blob_out),
    )
    if not ok:
        err = ctypes.get_last_error()
        raise OSError(err, f"CryptProtectData/CryptUnprotectData failed ({err})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def encrypt(value: str) -> str:
    """Return a DPAPI-protected, base64 encoded value; fall back to plain text."""
    if not value:
        return ""
    if value.startswith(PREFIX):
        return value
    try:
        protected = _crypt(True, value.encode("utf-8"))
        return PREFIX + base64.b64encode(protected).decode("ascii")
    except Exception as exc:  # pragma: no cover - depends on host policy
        log.warning("DPAPI encryption unavailable: %s", exc)
        return value


def decrypt(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(PREFIX):
        return value
    try:
        raw = base64.b64decode(value[len(PREFIX):])
        return _crypt(False, raw).decode("utf-8")
    except Exception as exc:  # pragma: no cover
        log.warning("Could not decrypt stored API key: %s", exc)
        return ""


def is_encrypted(value: str) -> bool:
    return bool(value and value.startswith(PREFIX))
