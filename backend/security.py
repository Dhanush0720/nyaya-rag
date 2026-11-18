"""Password hashing (scrypt, standard library) and JWT helpers (PyJWT)."""
import base64
import binascii
import hashlib
import hmac
import os
import time
from typing import Optional

import jwt

_N, _R, _P = 2 ** 14, 8, 1


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
        return hmac.compare_digest(actual, expected)
    except (ValueError, binascii.Error):
        return False


def make_token(user_id: str, secret: str, hours: int = 12) -> str:
    if hours <= 0:
        raise ValueError("Token lifetime must be a positive number of hours")
    now = int(time.time())
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + hours * 3600}, secret, algorithm="HS256")


def read_token(token: str, secret: str) -> Optional[str]:
    try:
        data = jwt.decode(token, secret, algorithms=["HS256"],
                          options={"require": ["exp", "sub"]})
        sub = data.get("sub")
        return str(sub) if sub is not None else None
    except jwt.PyJWTError:
        return None
