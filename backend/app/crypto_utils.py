# CR-FINAL-FIX: 将配置密钥加密改为真正AES-256-GCM并提供解密工具。
from __future__ import annotations

import base64
import hashlib
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import settings


def _derive_key() -> bytes:
    seed = os.getenv('ZHIDANG_SECRET_KEY') or settings.jwt_secret
    return hashlib.sha256(seed.encode('utf-8')).digest()


def encrypt_secret(value: str) -> str:
    key = _derive_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, value.encode('utf-8'), None)
    return 'aesgcm:' + base64.b64encode(nonce + ciphertext).decode('ascii')


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    if not value.startswith('aesgcm:'):
        return value
    raw = base64.b64decode(value.split(':', 1)[1])
    nonce, ciphertext = raw[:12], raw[12:]
    aesgcm = AESGCM(_derive_key())
    return aesgcm.decrypt(nonce, ciphertext, None).decode('utf-8')
