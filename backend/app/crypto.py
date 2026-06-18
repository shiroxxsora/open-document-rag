from __future__ import annotations

import base64
import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings


def derive_fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet(settings: Settings) -> Fernet:
    return Fernet(derive_fernet_key(settings.auth_secret_key))


def encrypt_secret(settings: Settings, value: str) -> str:
    if not value:
        return ""
    return get_fernet(settings).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(settings: Settings, value: str | None) -> str:
    if not value:
        return ""
    try:
        return get_fernet(settings).decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt stored secret.") from exc


def mask_secret(value: str | None, *, visible: int = 4) -> str | None:
    if not value:
        return None
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}...{value[-visible:]}"


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_api_token() -> tuple[str, str, str]:
    suffix = secrets.token_urlsafe(32)
    raw = f"srbs_live_{suffix}"
    return raw, hash_token(raw), raw[:16]
