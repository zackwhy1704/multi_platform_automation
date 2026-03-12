"""
Fernet-based encryption for platform credentials.
"""

import os
import logging
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")

if _ENCRYPTION_KEY:
    cipher = Fernet(
        _ENCRYPTION_KEY.encode() if isinstance(_ENCRYPTION_KEY, str) else _ENCRYPTION_KEY
    )
else:
    logger.warning("ENCRYPTION_KEY not set — generating ephemeral key (not for production)")
    cipher = Fernet(Fernet.generate_key())


def encrypt(plaintext: str) -> bytes:
    return cipher.encrypt(plaintext.encode())


def decrypt(token: bytes) -> str:
    return cipher.decrypt(token).decode()
