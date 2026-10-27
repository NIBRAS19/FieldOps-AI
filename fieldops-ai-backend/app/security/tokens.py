from datetime import timedelta

import jwt

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.types import utcnow

ISS, AUD = "fieldops-demo", "fieldops-api"


def issue(user_id: str, workspace_id: str) -> tuple[str, int]:
    s = get_settings()
    now = utcnow()
    exp = now + timedelta(minutes=s.token_ttl_minutes)
    return jwt.encode({"sub": user_id, "ws": workspace_id, "iat": now, "exp": exp, "iss": ISS, "aud": AUD}, s.secret_key, algorithm="HS256"), s.token_ttl_minutes * 60


def decode(token: str) -> dict:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"], audience=AUD, issuer=ISS, options={"require": ["exp", "sub", "iss", "aud"]})
    except jwt.PyJWTError as e:
        raise AppError("UNAUTHENTICATED", "Invalid or expired token.", 401) from e
