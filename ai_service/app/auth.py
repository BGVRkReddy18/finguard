"""Verify the JWTs issued by the Django backend, so users log in once and call both services."""
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings

bearer = HTTPBearer(auto_error=False)


class AuthError(Exception):
    pass


def decode_user_id(token: str, settings: Settings) -> int:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AuthError(f"Invalid token: {exc}") from exc
    if claims.get("token_type") != "access" or "user_id" not in claims:
        raise AuthError("Not an access token")
    return int(claims["user_id"])


def current_user_id(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
) -> int:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        return decode_user_id(creds.credentials, settings)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
