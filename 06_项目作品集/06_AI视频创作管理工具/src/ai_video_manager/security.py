from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from pathlib import Path


SECRET_PREFIX = "enc:v1:"
KEY_FILE = "local_secret.key"


def protect_secret(secret: str, workspace_root: str | Path) -> str:
    if not secret or secret.startswith(SECRET_PREFIX):
        return secret
    key = _load_or_create_key(workspace_root)
    nonce = secrets.token_bytes(16)
    plaintext = secret.encode("utf-8")
    ciphertext = _xor(plaintext, _keystream(key, nonce, len(plaintext)))
    tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()[:16]
    payload = base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")
    return f"{SECRET_PREFIX}{payload}"


def reveal_secret(value: str, workspace_root: str | Path) -> str:
    if not value or not value.startswith(SECRET_PREFIX):
        return value
    raw = base64.urlsafe_b64decode(value.removeprefix(SECRET_PREFIX).encode("ascii"))
    nonce = raw[:16]
    tag = raw[16:32]
    ciphertext = raw[32:]
    key = _load_or_create_key(workspace_root)
    expected = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expected):
        raise ValueError("Encrypted secret failed integrity check")
    plaintext = _xor(ciphertext, _keystream(key, nonce, len(ciphertext)))
    return plaintext.decode("utf-8")


def _load_or_create_key(workspace_root: str | Path) -> bytes:
    config_dir = Path(workspace_root) / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / KEY_FILE
    if path.exists():
        return base64.urlsafe_b64decode(path.read_text(encoding="ascii").encode("ascii"))
    key = secrets.token_bytes(32)
    path.write_text(base64.urlsafe_b64encode(key).decode("ascii"), encoding="ascii")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    chunks: list[bytes] = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < length:
        counter_bytes = counter.to_bytes(8, "big")
        chunks.append(hmac.new(key, nonce + counter_bytes, hashlib.sha256).digest())
        counter += 1
    return b"".join(chunks)[:length]


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right, strict=True))
