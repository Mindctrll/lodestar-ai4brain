"""Encrypt users' API keys at rest (AGENTS.md rule 9; docs/plan/04, app.llm_credentials).

AES-256-GCM with a server master key from NAJMA_MASTER_KEY (base64, 32 bytes). The user id and
provider are bound in as associated data, so a ciphertext can't be moved to another account.
"""

import base64
import os
from dataclasses import dataclass
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.llm.redaction import register_secret

MASTER_KEY_VERSION = 1


class VaultUnavailable(RuntimeError):
    """No master key is configured, so keys can't be stored or read."""


@dataclass(frozen=True)
class SealedKey:
    ciphertext: bytes
    nonce: bytes
    master_key_version: int
    last4: str


def _master_key(raw: str | None) -> bytes:
    if not raw:
        raise VaultUnavailable("NAJMA_MASTER_KEY is not set")
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise VaultUnavailable("NAJMA_MASTER_KEY must decode to 32 bytes")
    return key


def _aad(user_id: UUID, provider: str) -> bytes:
    return f"{user_id}:{provider}".encode()


class Vault:
    def __init__(self, master_key_b64: str | None) -> None:
        self._raw = master_key_b64

    @property
    def available(self) -> bool:
        try:
            _master_key(self._raw)
        except VaultUnavailable:
            return False
        return True

    def seal(self, user_id: UUID, provider: str, api_key: str) -> SealedKey:
        api_key = api_key.strip()
        if len(api_key) < 8:
            raise ValueError("That doesn't look like an API key.")
        register_secret(api_key)
        nonce = os.urandom(12)
        ciphertext = AESGCM(_master_key(self._raw)).encrypt(
            nonce, api_key.encode(), _aad(user_id, provider)
        )
        return SealedKey(ciphertext, nonce, MASTER_KEY_VERSION, api_key[-4:])

    def open(self, user_id: UUID, provider: str, ciphertext: bytes, nonce: bytes) -> str:
        api_key = (
            AESGCM(_master_key(self._raw))
            .decrypt(nonce, ciphertext, _aad(user_id, provider))
            .decode()
        )
        register_secret(api_key)
        return api_key
