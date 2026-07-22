import secrets

import pytest

from app.agent_swarm.services.heirloom_sync import (
    HeirloomError,
    IPFSBlockchainHeirloomStore,
    PostgresEncryptedHeirloomStore,
    _content_hash,
)

VALID_KEY = secrets.token_bytes(32)


def test_content_hash_stable_regardless_of_key_order():
    a = {"weight": 1.5, "role": "query_analyzer"}
    b = {"role": "query_analyzer", "weight": 1.5}
    assert _content_hash(a) == _content_hash(b)


def test_content_hash_changes_when_content_changes():
    assert _content_hash({"weight": 1.5}) != _content_hash({"weight": 1.6})


def test_encrypt_decrypt_roundtrip():
    store = PostgresEncryptedHeirloomStore(device_key=VALID_KEY)
    snapshot = {"agent_id": "abc-123", "current_weight": 1.234, "role": "query_analyzer"}
    encrypted = store._encrypt(snapshot)
    assert encrypted != snapshot
    decrypted = store._decrypt(encrypted)
    assert decrypted == snapshot


def test_encrypt_produces_different_ciphertext_each_call():
    # AES-GCM must use a fresh nonce per encryption -- reusing one is a
    # real cryptographic vulnerability, so two encryptions of the same
    # plaintext must never produce identical ciphertext.
    store = PostgresEncryptedHeirloomStore(device_key=VALID_KEY)
    snapshot = {"weight": 1.0}
    assert store._encrypt(snapshot) != store._encrypt(snapshot)


def test_decrypt_fails_with_wrong_key():
    store_a = PostgresEncryptedHeirloomStore(device_key=VALID_KEY)
    store_b = PostgresEncryptedHeirloomStore(device_key=secrets.token_bytes(32))
    encrypted = store_a._encrypt({"weight": 1.0})
    with pytest.raises(Exception):  # cryptography raises InvalidTag
        store_b._decrypt(encrypted)


def test_missing_device_key_raises_heirloom_error(monkeypatch):
    from app import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("HEIRLOOM_DEVICE_KEY", "")
    with pytest.raises(HeirloomError, match="HEIRLOOM_DEVICE_KEY"):
        PostgresEncryptedHeirloomStore()
    config.get_settings.cache_clear()


def test_invalid_hex_device_key_raises_heirloom_error(monkeypatch):
    from app import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("HEIRLOOM_DEVICE_KEY", "not-valid-hex!!")
    with pytest.raises(HeirloomError, match="hex"):
        PostgresEncryptedHeirloomStore()
    config.get_settings.cache_clear()


def test_ipfs_blockchain_store_is_a_documented_stub_not_a_working_backend():
    with pytest.raises(NotImplementedError, match="ROADMAP.md"):
        IPFSBlockchainHeirloomStore()
