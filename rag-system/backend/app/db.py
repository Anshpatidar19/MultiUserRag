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
from supabase.lib.client_options import ClientOptions
from app.config import get_settings

settings = get_settings()


@lru_cache
def get_service_client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def get_user_client(access_token: str) -> Client:
    """
    Build a request-scoped client authenticated as the calling user.
    Not cached (and not cacheable) because the token differs per request.

    IMPORTANT: `create_client` sets every sub-client's Authorization
    header (postgrest, storage, auth) from `options.headers` at
    construction time. Calling `client.postgrest.auth(access_token)`
    *after* construction only updates the postgrest session -- it does
    NOT reach the storage client, which would otherwise keep sending
    the anon key and get silently rejected by the "documents" bucket's
    RLS policies (auth.uid() is null for the anon key). Passing the
    user's JWT via ClientOptions up front makes every sub-client --
    Postgres queries AND Storage uploads/downloads/deletes -- run as
    that user.
    """
    options = ClientOptions(headers={"Authorization": f"Bearer {access_token}"})
    client = create_client(settings.supabase_url, settings.supabase_anon_key, options=options)
    client.postgrest.auth(access_token)
    return client