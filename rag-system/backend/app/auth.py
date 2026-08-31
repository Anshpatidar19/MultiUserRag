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

PERFORMANCE (this used to be the #1 source of "everything feels slow"):
--------------------------------------------------------------------
Before this file was changed, EVERY single request -- opening the
sidebar, listing sessions, loading a chat's messages, sending a chat
message, polling document status -- paid for two things from scratch:

1. A fresh `create_client(...)` call in db.py, which spins up new
   httpx clients under the hood for postgrest/storage/auth.
2. A network round-trip to Supabase Auth's `/user` endpoint just to
   re-verify the *same* access token that had already been verified on
   the previous request a second ago.

A user's access token doesn't change between requests (Supabase mints
one JWT that's valid for ~1 hour and reused across all calls until it's
refreshed), so re-verifying it and rebuilding the client on every single
request was pure repeated work. We now cache both the verification
result and the constructed client, keyed by the raw token, in a
short-TTL in-memory cache:

- TTL is intentionally short (5 minutes) so a revoked/expired token is
  never trusted for long -- this is a latency optimization, not a
  cache-forever shortcut. Supabase's own JWT expiry (~1hr) still bounds
  the outer limit regardless.
- Keyed by the token itself (not user_id), so a logged-out/expired
  token can never satisfy a cache lookup for a *different*, currently
  valid token.
- Per-process, in-memory (cachetools.TTLCache) -- fine for a single
  backend instance; a multi-instance deployment would swap this for
  Redis with the same token-keyed contract, same as bm25_cache.py's
  documented single-instance caveat.
"""

from dataclasses import dataclass

from cachetools import TTLCache
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client

from app.db import get_user_client

bearer_scheme = HTTPBearer(auto_error=False)

# 5 minutes: long enough to remove the auth round-trip from every request
# in a normal chat session, short enough that a revoked token stops
# working within a bounded, small window.
_AUTH_CACHE_TTL_SECONDS = 300
_AUTH_CACHE_MAXSIZE = 4096

# token -> (user_id, email)
_verified_user_cache: TTLCache = TTLCache(maxsize=_AUTH_CACHE_MAXSIZE, ttl=_AUTH_CACHE_TTL_SECONDS)
# token -> Client (already constructed + authenticated as that user)
_client_cache: TTLCache = TTLCache(maxsize=_AUTH_CACHE_MAXSIZE, ttl=_AUTH_CACHE_TTL_SECONDS)


@dataclass
class CurrentUser:
    id: str
    email: str | None
    access_token: str
    db: Client  # RLS-scoped client, already authenticated as this user


def _get_or_build_client(token: str) -> Client:
    client = _client_cache.get(token)
    if client is None:
        client = get_user_client(token)
        _client_cache[token] = client
    return client


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    token = creds.credentials

    cached = _verified_user_cache.get(token)
    if cached is not None:
        user_id, email = cached
        return CurrentUser(id=user_id, email=email, access_token=token, db=_get_or_build_client(token))

    db = _get_or_build_client(token)

    try:
        resp = db.auth.get_user(token)
    except Exception as exc:  # noqa: BLE001 - surface as a clean 401
        # Don't cache failures -- a transient network hiccup shouldn't
        # lock a valid token out for the TTL window.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    if resp is None or resp.user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    _verified_user_cache[token] = (resp.user.id, resp.user.email)
    return CurrentUser(id=resp.user.id, email=resp.user.email, access_token=token, db=db)