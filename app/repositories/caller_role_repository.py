"""Who is asking, and are they allowed to see the whole session.

This service has had no authorization of any kind: every route trusts the
`x-user-id` header and the gateway's JWT check. That is fine while every endpoint
is organization-wide, but the dashboard now answers "what did this session take",
and a cashier must not be able to read a colleague's takings by editing a query
string.

Membership lives in management-be's `organization_members` / `roles`. This reads
them directly rather than calling management-be over HTTP — no per-request
network hop on a dashboard that fires four panels, and no need to forward the
caller's bearer token through this service. support-be already reads
`organization_members` the same way (`_assert_membership`), so the precedent is
established.

**The coupling is real and deliberate**: a rename in management-be's membership
schema breaks this file, and nothing in either repo's CI would catch it. The
query is therefore kept to the three columns that are load-bearing, so the
surface that can break is as small as possible.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple

from sqlalchemy import text

from app.configuration.database_connection import DatabaseConnection

logger = logging.getLogger(__name__)

#: Role names that may see a whole session rather than only their own rows.
#: Mirrors management-be's `RBACService` (`isAdmin = owner || admin`), plus
#: `platform_admin`, which holds every permission globally.
ADMIN_ROLES = frozenset({"owner", "admin", "platform_admin"})

#: How long a resolved role is trusted inside one Lambda container. Roles change
#: rarely and a dashboard refresh fires several panels at once, so re-reading per
#: panel is waste; five minutes also bounds how long a revoked admin keeps the
#: wider view.
CACHE_TTL_SECONDS = 300

#: (user_id, organization_id) -> (is_admin, expires_at). Process-local, so it
#: dies with the container and never has to be invalidated across instances.
_cache: Dict[Tuple[str, str], Tuple[bool, float]] = {}


def _lookup(organization_id: str, user_id: str) -> bool:
    query = text("""
        SELECT
            -- Owner of the organization outright, membership row or not.
            EXISTS (
                SELECT 1 FROM organizations o
                WHERE o.id = :org_id AND o.owner_id = :user_id
            ) AS is_owner,
            -- Or a member holding an administrative role.
            EXISTS (
                SELECT 1
                FROM organization_members m
                JOIN roles r ON r.id = m.role_id
                WHERE m.organization_id = :org_id
                  AND m.user_id = :user_id
                  AND r.name = ANY(:admin_roles)
            ) AS has_admin_role
    """)
    with DatabaseConnection() as db:
        row = db.session.execute(query, {
            "org_id": organization_id,
            "user_id": user_id,
            "admin_roles": list(ADMIN_ROLES),
        }).one()
    return bool(row.is_owner or row.has_admin_role)


def is_admin(organization_id: Optional[str], user_id: Optional[str]) -> bool:
    """Whether this caller may see organization- and session-wide figures.

    **Fails closed.** A missing user, an unresolvable role or a database error
    all answer False, so a lookup failure narrows what somebody can see instead
    of widening it. The alternative — defaulting to admin when the check breaks —
    turns an outage into a data leak.
    """
    if not organization_id or not user_id:
        return False

    key = (user_id, organization_id)
    cached = _cache.get(key)
    now = time.time()
    if cached and cached[1] > now:
        return cached[0]

    try:
        result = _lookup(organization_id, user_id)
    except Exception:  # noqa: BLE001
        # Deliberately not cached: a transient failure should not pin this
        # caller to "not admin" for the next five minutes.
        logger.exception(
            "Could not resolve the role of %s in %s; treating as non-admin",
            user_id, organization_id,
        )
        return False

    _cache[key] = (result, now + CACHE_TTL_SECONDS)
    return result


def clear_cache() -> None:
    """Drop the memo. For tests, and for a caller that just changed a role."""
    _cache.clear()
