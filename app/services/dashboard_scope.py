"""What slice of the data a dashboard request is allowed to see.

Three scopes, resolved server-side:

    org                 the whole business
    session             one session, every till in it
    session + own       one session, only this caller's rows

The rule: **only an admin may widen past their own rows.** A cashier asking for
session-wide figures is narrowed to their own, silently — not refused. Refusing
would break a legitimate flow (a till handed over mid-shift, a device switched)
with an error the cashier cannot act on, and the narrowed answer is the one they
are entitled to anyway.

Narrowing here rather than in the frontend is the point. The frontend already
knows the caller's role and sends the right filters, but anyone can call the
endpoint directly; a filter applied only in the client is decoration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.repositories import caller_role_repository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DashboardScope:
    """The filters a panel query should actually apply.

    `session_id` and `user_id` are what the SQL binds. `requested_session_id`
    with `user_id` set means the caller asked for a session they may only see
    their own share of — the response says so, so the UI can label the figures
    honestly instead of implying they are the session's total.
    """

    organization_id: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    is_admin: bool = False

    @property
    def is_session_scoped(self) -> bool:
        return self.session_id is not None

    @property
    def is_own_only(self) -> bool:
        return self.user_id is not None

    def describe(self) -> str:
        """For the response, so the client can label what it is showing."""
        if not self.session_id:
            return "organization"
        return "session_user" if self.user_id else "session"


def resolve(
    organization_id: str,
    caller_user_id: Optional[str],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> DashboardScope:
    """Resolve the requested scope into the one the caller may have.

    - No `session_id` asked for → organization-wide, but only for an admin. A
      non-admin gets their own rows across the organization, which is the
      honest answer to "what have I sold" when they are not in a session.
    - `session_id` asked for → that session; narrowed to the caller unless they
      are an admin. A `user_id` a non-admin supplies is ignored in favour of
      their own id, so passing somebody else's is not a way in.
    """
    caller_is_admin = caller_role_repository.is_admin(organization_id, caller_user_id)

    if caller_is_admin:
        # An admin may look at anyone, including one specific person — that is a
        # legitimate question about their own staff.
        return DashboardScope(
            organization_id=organization_id,
            session_id=session_id,
            user_id=user_id,
            is_admin=True,
        )

    if user_id and user_id != caller_user_id:
        # Not an error worth failing on: log it and answer the question they
        # were entitled to ask.
        logger.info(
            "Non-admin %s asked for user %s in org %s; narrowed to self",
            caller_user_id, user_id, organization_id,
        )

    return DashboardScope(
        organization_id=organization_id,
        session_id=session_id,
        user_id=caller_user_id,
        is_admin=False,
    )
