"""
auth.py

FastAPI dependency that turns "Authorization: Bearer <supabase jwt>" into
a verified user_id + a request-scoped, RLS-bound Supabase client. Every
document/chat/session route depends on `get_current_user` so there is
exactly one place that decides whether a request is authenticated --
new routes can't accidentally forget to check.

We verify the JWT by asking Supabase Auth itself (`auth.get_user`)
rather than decoding it locally, which means a token revoked or expired
server-side is rejected here too, not just on next refresh.
"""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client

from app.db import get_user_client

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: str
    email: str | None
    access_token: str
    db: Client  # RLS-scoped client, already authenticated as this user


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    token = creds.credentials
    db = get_user_client(token)

    try:
        resp = db.auth.get_user(token)
    except Exception as exc:  # noqa: BLE001 - surface as a clean 401
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    if resp is None or resp.user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    return CurrentUser(id=resp.user.id, email=resp.user.email, access_token=token, db=db)
