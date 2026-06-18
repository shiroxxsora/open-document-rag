from app.config import load_settings
from app.crypto import decrypt_secret, encrypt_secret, hash_token, mask_secret


def test_fernet_roundtrip():
    settings = load_settings()
    original = "sk-test-secret-value"
    encrypted = encrypt_secret(settings, original)
    assert encrypted
    assert encrypted != original
    assert decrypt_secret(settings, encrypted) == original


def test_mask_secret():
    assert mask_secret("abcdefghijklmnop") == "abcd...mnop"
    assert mask_secret("") is None
    assert mask_secret(None) is None


def test_hash_token_is_stable():
    assert hash_token("srbs_live_example") == hash_token("srbs_live_example")
    assert hash_token("srbs_live_example") != hash_token("srbs_live_other")
