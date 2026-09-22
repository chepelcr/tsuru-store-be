"""Route-level RBAC guard for store-be (first slice of roadmap TSR-031)."""

from __future__ import annotations

from fastapi import HTTPException

from app.repositories import permission_repository


def require_permission(
    organization_id: str, user_id: str, module: str, action: str, submodule: str
) -> None:
    """Raise 403 unless the caller holds `module:submodule:action` in the org.

    Always enforced — unlike management-be's `RBAC_ENFORCEMENT=log` rollout,
    the routes guarded here are new and had no prior callers to break.
    """
    if not permission_repository.has_permission(
        organization_id, user_id, module, action, submodule
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PERMISSION_DENIED",
                "message": f"Missing permission {module}:{submodule}:{action}",
                "permission": f"{module}:{submodule}:{action}",
            },
        )
