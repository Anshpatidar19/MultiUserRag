"""
db.py

Two Supabase clients, deliberately kept separate:

- `get_user_client(jwt)` uses the caller's own access token, so every
  query runs AS that user and is therefore subject to Postgres Row
  Level Security. This is the client every route handler should use for
  reading/writing documents, sessions, and messages -- it's what makes
  "even a direct DB query can't leak another user's rows" true, rather
  than just an application-layer promise.
- `get_service_client()` uses the service-role key, which bypasses RLS.
  It exists only for trusted server-side maintenance tasks (e.g. an
  admin cleanup job) and must never be used to serve a per-user request.

Keeping these distinct prevents the easy mistake of "just use the admin
client everywhere for convenience," which would quietly defeat RLS.
"""

from functools import lru_cache
from supabase import create_client, Client
from app.config import get_settings

settings = get_settings()


@lru_cache
def get_service_client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def get_user_client(access_token: str) -> Client:
    """
    Build a request-scoped client authenticated as the calling user.
    Not cached (and not cacheable) because the token differs per request.
    """
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    client.postgrest.auth(access_token)
    return client
