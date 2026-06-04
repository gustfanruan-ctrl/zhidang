from __future__ import annotations

# Backward-compatible crypto module; canonical implementation lives in crypto_utils.
from .crypto_utils import decrypt_secret, encrypt_secret

__all__ = ["encrypt_secret", "decrypt_secret"]
