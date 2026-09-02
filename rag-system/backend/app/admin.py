"""
admin.py

Admin authorization layer, deliberately separate from auth.py's
`get_current_user`. Being logged in only proves "this is a valid
Supabase user" -- it says nothing about whether that user should be
able to see every OTHER user's documents, sessions, or account list.
`get_current_admin` wraps `get_current_user` and additionally requires
the caller's id to be present in the `admin_users` table (see
supabase/admin_schema.sql), checked via the SERVICE-ROLE client so the
check itself can't be defeated by a missing/misconfigured RLS policy
on that table (see admin_schema.sql -- that table has zero policies on
purpose, so only the service-role client can read it at all).

Bootstrapping the first admin: there is no self-service "become an
admin" endpoint anywhere in this app, on purpose. The first (and any
subsequent) admin is added directly in Supabase's SQL editor:

    insert into admin_users (user_id) values ('<their auth.users.id>');

Cached with a short TTL (same pattern as auth.py's token cache) so
every admin page click doesn't pay for a fresh Postgres round trip,
while a revoked admin stops working within a bounded window.
"""

from cachetools import TTLCache
from fastapi import Depends, HTTPException, status

from app.auth import CurrentUser, get_current_user
from app.db import get_service_client

_ADMIN_CACHE_TTL_SECONDS = 60
_admin_flag_cache: TTLCache = TTLCache(maxsize=4096, ttl=_ADMIN_CACHE_TTL_SECONDS)


def _is_admin(user_id: str) -> bool:
    cached = _admin_flag_cache.get(user_id)
    if cached is not None:
        return cached

    db = get_service_client()
    resp = db.table("admin_users").select("user_id").eq("user_id", user_id).execute()
    is_admin = bool(resp.data)
    _admin_flag_cache[user_id] = is_admin
    return is_admin


async def get_current_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not _is_admin(user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user