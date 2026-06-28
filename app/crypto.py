"""WeAPI encryption compatible with NetEase web clients."""

from __future__ import annotations

import base64
import json
import secrets

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

_WEAPI_NONCE = b"0CoJUm6Qyw8W8jud"
_WEAPI_IV = b"0102030405060708"
_WEAPI_PUBKEY = 0x10001
_WEAPI_MODULUS = int(
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725"
    "152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312"
    "ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424"
    "d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8"
    "e7",
    16,
)


def _aes_encrypt(raw: bytes, key: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_CBC, _WEAPI_IV)
    return cipher.encrypt(pad(raw, AES.block_size))


def _rsa_encrypt(sec_key: bytes) -> str:
    reversed_key = sec_key[::-1]
    value = int.from_bytes(reversed_key, "big")
    encrypted = pow(value, _WEAPI_PUBKEY, _WEAPI_MODULUS)
    return format(encrypted, "x").zfill(256)


def weapi_encrypt(payload: dict) -> dict:
    """Encrypt a dict for NetEase WeAPI (params + encSecKey)."""
    plain = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sec_key = secrets.token_hex(8).encode("ascii")
    first_pass = _aes_encrypt(plain, _WEAPI_NONCE)
    second_pass = _aes_encrypt(base64.b64encode(first_pass), sec_key)
    return {
        "params": base64.b64encode(second_pass).decode("utf-8"),
        "encSecKey": _rsa_encrypt(sec_key),
    }
