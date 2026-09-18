"""Queries behind the POS dashboard.

Each method answers ONE question, because the dashboard's panels are independent
questions: what have we sold, what is in flight, what is selling, who is on a
till right now. They used to be a single call that answered all four or none.

What was wrong before
---------------------
The previous implementation was written for a different schema. It read
`sales_orders` and `order_items`, **neither of which exists in this database**,
and the failure was swallowed ("expected if sales_orders ... doesn't exist yet"),
so every figure came back empty and looked like a quiet day rather than a broken
query. Worse, the whole thing was gated on there being an **active session with
an active assignment**: with 45 real orders in the table and 44 of them carrying
no `assignment_id`, the endpoint returned zeros by design.

Orders live in `crossdocking_orders` (`company_id` is the organization) with
lines in `crossdocking_order_lines`. Sales figures come from there, so they are
true whether or not a cashier has a session open. Sessions and assignments answer
only the "who is on a till" question, which is the one they are actually about.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.configuration.database_connection import DatabaseConnection

logger = logging.getLogger(__name__)

# `order_status` values that represent money actually earned. A cancelled order
# is not revenue, and counting it inflates both the total and the average ticket.
REVENUE_STATUSES = ("delivered", "invoiced", "completed")

# Statuses that mean "still in flight" — the ones an operator is watching.
OPEN_STATUSES = ("pending", "processing", "in_progress", "dispatched", "sent")

# `status` = 1 is the active row in this schema (soft-delete lives in deleted_on).
ROW_ACTIVE = 1

# Date filtering uses `created_on` (a real timestamp), never `creation_date`.
# `creation_date` is a VARCHAR holding "DD/MM/YYYY", so casting it to a date does
# not fail — it silently misreads the month under Postgres's default DateStyle
# ("09/02/2026" becomes 2 September, not 9 February). A dashboard that quietly
# reports the wrong month is worse than one that errors.


class DashboardRepository(DatabaseConnection):
    """Read-only aggregates for the dashboard panels."""

    def __init__(self):
        super().__init__()

    # ── Sales ───────────────────────────────────────────────────────────────

    def sales_summary(
        self,
        organization_id: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Revenue, order count and average ticket.

        Counted from the orders themselves, so the figure is right whether or not
        anybody has a session open. Cancelled orders are excluded — they are not
        revenue, and including them drags the average ticket toward a number that
        describes nothing.
        """
        query = text("""
            SELECT
                COUNT(*)                                AS orders,
                COALESCE(SUM(grand_total), 0)           AS revenue,
                COALESCE(SUM(total_quantities), 0)      AS units,
                MAX(created_on)                         AS last_order_at
            FROM crossdocking_orders
            WHERE company_id = :org_id
              AND deleted_on IS NULL
              AND order_status = ANY(:statuses)
              AND (CAST(:date_from AS date) IS NULL OR created_on >= CAST(:date_from AS date))
              AND (CAST(:date_to   AS date) IS NULL OR created_on <  CAST(:date_to AS date) + 1)
        """)
        row = self.session.execute(query, {
            "org_id": organization_id,
            "statuses": list(REVENUE_STATUSES),
            "date_from": date_from,
            "date_to": date_to,
        }).one()

        orders = int(row.orders or 0)
        revenue = float(row.revenue or 0)
        return {
            "orders": orders,
            "revenue": revenue,
            # Guarded: the average of nothing is not zero, but zero is the only
            # honest thing to render in an empty state.
            "average_ticket": (revenue / orders) if orders else 0.0,
            "units": float(row.units or 0),
            "last_order_at": row.last_order_at,
        }

    def order_status_breakdown(self, organization_id: str) -> List[Dict[str, Any]]:
        """Every status with its count and value, busiest first.

        This is the panel that answers "I have orders in process" — which the old
        dashboard could not show at all, because it only ever reported a single
        revenue total drawn from a table that did not exist.
        """
        query = text("""
            SELECT
                order_status,
                COUNT(*)                      AS orders,
                COALESCE(SUM(grand_total), 0) AS value
            FROM crossdocking_orders
            WHERE company_id = :org_id AND deleted_on IS NULL
            GROUP BY order_status
            ORDER BY orders DESC
        """)
        rows = self.session.execute(query, {"org_id": organization_id}).fetchall()
        return [
            {
                "status": row.order_status or "unknown",
                "orders": int(row.orders or 0),
                "value": float(row.value or 0),
                "is_open": (row.order_status or "") in OPEN_STATUSES,
            }
            for row in rows
        ]

    def top_products(self, organization_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Best sellers by revenue, from the order lines.

        Joined through the orders so the organization filter and the
        revenue-status filter both apply — a ranking that counts cancelled orders
        recommends restocking something nobody bought.
        """
        query = text("""
            SELECT
                l.product_id,
                COALESCE(MAX(l.description), MAX(p.name))     AS name,
                MAX(p.image_url)                              AS image_url,
                COALESCE(SUM(l.quantity_ordered), 0)          AS units,
                COALESCE(SUM(l.line_total), 0)                AS revenue
            FROM crossdocking_order_lines l
            JOIN crossdocking_orders o ON o.order_id = l.order_id
            -- `products` keys on `id`, not `product_id`.
            LEFT JOIN products p ON p.id = l.product_id
            WHERE o.company_id = :org_id
              AND o.deleted_on IS NULL
              AND l.deleted_on IS NULL
              AND o.order_status = ANY(:statuses)
            GROUP BY l.product_id
            ORDER BY revenue DESC
            LIMIT :limit
        """)
        rows = self.session.execute(query, {
            "org_id": organization_id,
            "statuses": list(REVENUE_STATUSES),
            "limit": limit,
        }).fetchall()
        return [
            {
                "product_id": str(row.product_id) if row.product_id else None,
                "name": row.name or "—",
                "image_url": row.image_url or "",
                "units": float(row.units or 0),
                "revenue": float(row.revenue or 0),
            }
            for row in rows
        ]

    def sales_by_day(self, organization_id: str, days: int = 14) -> List[Dict[str, Any]]:
        """Revenue per day for the trend chart, oldest first."""
        query = text("""
            SELECT
                CAST(created_on AS date)      AS day,
                COUNT(*)                      AS orders,
                COALESCE(SUM(grand_total), 0) AS revenue
            FROM crossdocking_orders
            WHERE company_id = :org_id
              AND deleted_on IS NULL
              AND order_status = ANY(:statuses)
              AND created_on >= CURRENT_DATE - CAST(:days AS integer)
            GROUP BY CAST(created_on AS date)
            ORDER BY day
        """)
        rows = self.session.execute(query, {
            "org_id": organization_id,
            "statuses": list(REVENUE_STATUSES),
            "days": days,
        }).fetchall()
        return [
            {
                "day": row.day.isoformat() if row.day else None,
                "orders": int(row.orders or 0),
                "revenue": float(row.revenue or 0),
            }
            for row in rows
        ]

    # ── Live tills ──────────────────────────────────────────────────────────

    def active_stations(self, organization_id: str,
                        session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Who is on a till right now, and what they have taken.

        This is the ONLY panel that legitimately depends on there being an open
        session — it is the question "who is working". An empty list means nobody
        is on a till, which is a real answer and no longer drags the sales figures
        to zero with it.

        Per-station takings come from orders carrying that `assignment_id`. Most
        orders do not carry one (they were not rung up on an assigned till), which
        is exactly why organization-wide revenue is a separate query.
        """
        query = text("""
            SELECT
                a.assignment_id,
                a.branch_id,
                a.user_id,
                s.session_id,
                s.name        AS session_name,
                s.context     AS session_context,
                a.start_time,
                COUNT(o.order_id)                     AS orders,
                COALESCE(SUM(o.grand_total), 0)       AS revenue,
                MAX(o.created_on)                     AS last_order_at
            FROM assignments a
            JOIN sales_sessions s ON s.session_id = a.session_id
            LEFT JOIN crossdocking_orders o
                   -- `crossdocking_orders.assignment_id` is VARCHAR while
                   -- `assignments.assignment_id` is UUID, so the join needs an
                   -- explicit cast; without it Postgres refuses the comparison.
                   ON o.assignment_id = CAST(a.assignment_id AS text)
                  AND o.deleted_on IS NULL
                  AND o.order_status = ANY(:statuses)
            WHERE a.organization_id = :org_id
              AND a.status = :active
              AND a.deleted_on IS NULL
              AND s.status = :active
              -- Row-active is not the same as still open: a finished session or
              -- a handed-over assignment keeps an active row but has an end
              -- time, and neither is somebody currently on a till.
              AND s.end_time IS NULL
              AND a.end_time IS NULL
              -- Cast both sides: an untyped NULL parameter compared against a
              -- uuid column leaves Postgres unable to infer the type at all.
              AND (CAST(:session_id AS text) IS NULL
                   OR CAST(s.session_id AS text) = CAST(:session_id AS text))
            GROUP BY a.assignment_id, a.branch_id, a.user_id,
                     s.session_id, s.name, s.context, a.start_time
            ORDER BY revenue DESC
        """)
        rows = self.session.execute(query, {
            "org_id": organization_id,
            "session_id": session_id,
            "statuses": list(REVENUE_STATUSES),
            "active": ROW_ACTIVE,
        }).fetchall()
        return [
            {
                "assignment_id": str(row.assignment_id),
                "branch_id": str(row.branch_id) if row.branch_id else None,
                "user_id": str(row.user_id) if row.user_id else None,
                "session_id": str(row.session_id),
                "session_name": row.session_name or "",
                "session_context": row.session_context or "",
                "started_at": row.start_time,
                "orders": int(row.orders or 0),
                "revenue": float(row.revenue or 0),
                "last_order_at": row.last_order_at,
            }
            for row in rows
        ]
