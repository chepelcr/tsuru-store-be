"""Granular RBAC check (module / submodule / action) for store-be routes.

store-be has had no module-level authorization: every route trusts the
`x-user-id` header and the gateway's JWT check (roadmap TSR-031). That was
tolerable while nothing it served was sensitive; editing a fiscal consecutive
is, so this implements management-be's effective-permission rule (V4 in the
rbac contract) directly in SQL, the same way `caller_role_repository` reads
membership — see that module for why this reads management-be's tables rather
than calling it over HTTP, and for the coupling that comes with it.

The rule, as management-be's `RBACService.hasPermission` resolves it:

    platform_admin user                       -> allow
    otherwise the caller's ACTIVE role in the org (organization_members.role_id;
    the org's owner_id counts as the `owner` role) must be active, and:
      the submodule must be AVAILABLE to the org —
          module.is_active AND submodule.is_active
          AND organization_modules(org, module).is_enabled      (no row = no)
          AND COALESCE(organization_submodules(org, sub).is_enabled, true)
      AND the action must be grantable on it (submodule_actions)
      AND the role is `owner`, OR holds a grant for (module, action) whose
          submodule is this one or NULL (module-wide).

**Fails closed**: a missing user, no membership, or a database error all deny.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple

from sqlalchemy import text

from app.configuration.database_connection import DatabaseConnection

logger = logging.getLogger(__name__)

#: Matches management-be's permission cache TTL (RBAC_CACHE_TTL_MS default 60s),
#: so a revoked grant stops working here no later than it does there.
CACHE_TTL_SECONDS = 60

_cache: Dict[Tuple[str, str, str, str, str], Tuple[bool, float]] = {}

_QUERY = text("""
    WITH caller AS (
        SELECT
            (SELECT u.role FROM users u WHERE u.id = :user_id) AS user_role,
            EXISTS (
                SELECT 1 FROM organizations o
                WHERE o.id = :org_id AND o.owner_id = :user_id
            ) AS owns_org,
            (
                SELECT r.id FROM organization_members m
                JOIN roles r ON r.id = m.role_id AND r.is_active
                WHERE m.organization_id = :org_id AND m.user_id = :user_id
                LIMIT 1
            ) AS role_id,
            (
                SELECT r.name FROM organization_members m
                JOIN roles r ON r.id = m.role_id AND r.is_active
                WHERE m.organization_id = :org_id AND m.user_id = :user_id
                LIMIT 1
            ) AS role_name
    ),
    target AS (
        SELECT mo.id AS module_id, s.id AS submodule_id, a.id AS action_id
        FROM modules mo
        JOIN submodules s ON s.module_id = mo.id AND s.name = :submodule AND s.is_active
        JOIN actions a ON a.name = :action
        JOIN submodule_actions sa ON sa.submodule_id = s.id AND sa.action_id = a.id
        JOIN organization_modules om
             ON om.organization_id = :org_id AND om.module_id = mo.id AND om.is_enabled
        LEFT JOIN organization_submodules os
             ON os.organization_id = :org_id AND os.submodule_id = s.id
        WHERE mo.name = :module AND mo.is_active
          AND COALESCE(os.is_enabled, true)
    )
    SELECT
        (SELECT user_role FROM caller) = 'platform_admin' AS is_platform_admin,
        EXISTS (SELECT 1 FROM target) AS available,
        (SELECT owns_org FROM caller) OR (SELECT role_name FROM caller) = 'owner' AS is_owner,
        EXISTS (
            SELECT 1 FROM role_permissions rp, target t
            WHERE rp.role_id = (SELECT role_id FROM caller)
              AND rp.module_id = t.module_id
              AND rp.action_id = t.action_id
              AND (rp.submodule_id IS NULL OR rp.submodule_id = t.submodule_id)
        ) AS granted
""")


def _lookup(organization_id: str, user_id: str, module: str, action: str, submodule: str) -> bool:
    with DatabaseConnection() as db:
        row = db.session.execute(_QUERY, {
            "org_id": organization_id,
            "user_id": user_id,
            "module": module,
            "action": action,
            "submodule": submodule,
        }).one()
    return _decide(row)


def _decide(row) -> bool:
    if row.is_platform_admin:
        return True
    if not row.available:
        return False
    return bool(row.is_owner or row.granted)


def has_permission(
    organization_id: Optional[str],
    user_id: Optional[str],
    module: str,
    action: str,
    submodule: str,
) -> bool:
    """Whether the caller may perform `module:submodule:action` in the org.

    Fails closed; transient failures are not cached (see caller_role_repository).
    """
    if not organization_id or not user_id:
        return False

    key = (user_id, organization_id, module, submodule, action)
    now = time.time()
    cached = _cache.get(key)
    if cached and cached[1] > now:
        return cached[0]

    try:
        result = _lookup(organization_id, user_id, module, action, submodule)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Could not resolve %s:%s:%s for %s in %s; denying",
            module, submodule, action, user_id, organization_id,
        )
        return False

    _cache[key] = (result, now + CACHE_TTL_SECONDS)
    return result


def clear_cache() -> None:
    """Drop the memo. For tests."""
    _cache.clear()
