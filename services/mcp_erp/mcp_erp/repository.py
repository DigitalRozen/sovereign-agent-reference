"""Database access. Each operation uses the least-privileged role that can perform it.

ai_reader        SELECT on the ai.* views
ai_writer        INSERT into ai.po_drafts and audit.events
erp_integration  the approval path only: INSERT into erp.purchase_orders, UPDATE draft status

Even if this code were wrong, the database grants still bound what each role can do
(see tests/cluster/test_data_boundaries.py).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .policy import DraftRequest


class DraftNotPending(Exception):
    """The draft does not exist or was already decided."""


class Repository(Protocol):
    async def inventory(self, material_id: str | None) -> list[dict]: ...
    async def open_orders(self) -> list[dict]: ...
    async def suppliers(self) -> list[dict]: ...
    async def supplier_for(self, material_id: str) -> str | None: ...
    async def insert_draft(self, request: DraftRequest, requested_by: str) -> dict: ...
    async def get_draft(self, draft_id: int) -> dict | None: ...
    async def approve_draft(self, draft_id: int, approver: str) -> dict: ...
    async def audit(self, actor: str, action: str, decision: str, detail: dict) -> None: ...


def _plain(row: dict[str, Any]) -> dict[str, Any]:
    """Make rows JSON-friendly for tool results."""
    out = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


@dataclass
class PostgresRepository:
    reader_dsn: str
    writer_dsn: str
    integration_dsn: str

    async def _fetch(self, dsn: str, sql: str, params: tuple = ()) -> list[dict]:
        async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
            cur = await conn.execute(sql, params)
            return [_plain(row) for row in await cur.fetchall()]

    async def inventory(self, material_id: str | None) -> list[dict]:
        sql = "SELECT * FROM ai.inventory"
        if material_id:
            return await self._fetch(
                self.reader_dsn, sql + " WHERE material_id = %s", (material_id,)
            )
        return await self._fetch(self.reader_dsn, sql + " ORDER BY material_id")

    async def open_orders(self) -> list[dict]:
        return await self._fetch(self.reader_dsn, "SELECT * FROM ai.open_orders ORDER BY due_date")

    async def suppliers(self) -> list[dict]:
        return await self._fetch(self.reader_dsn, "SELECT * FROM ai.suppliers ORDER BY supplier_id")

    async def supplier_for(self, material_id: str) -> str | None:
        rows = await self._fetch(
            self.reader_dsn,
            "SELECT supplier_id FROM ai.inventory WHERE material_id = %s",
            (material_id,),
        )
        return rows[0]["supplier_id"] if rows else None

    async def insert_draft(self, request: DraftRequest, requested_by: str) -> dict:
        rows = await self._fetch(
            self.writer_dsn,
            """
            INSERT INTO ai.po_drafts
                (material_id, supplier_id, quantity_kg, rationale, requested_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING draft_id, material_id, supplier_id, quantity_kg, status, created_at
            """,
            (
                request.material_id,
                request.supplier_id,
                request.quantity_kg,
                request.rationale,
                requested_by,
            ),
        )
        return rows[0]

    async def get_draft(self, draft_id: int) -> dict | None:
        rows = await self._fetch(
            self.reader_dsn, "SELECT * FROM ai.po_drafts WHERE draft_id = %s", (draft_id,)
        )
        return rows[0] if rows else None

    async def approve_draft(self, draft_id: int, approver: str) -> dict:
        """Atomically move a pending draft to submitted and create the ERP order."""
        async with await psycopg.AsyncConnection.connect(
            self.integration_dsn, row_factory=dict_row
        ) as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    """
                    UPDATE ai.po_drafts SET status = 'submitted'
                    WHERE draft_id = %s AND status = 'pending_approval'
                    RETURNING draft_id, material_id, supplier_id, quantity_kg
                    """,
                    (draft_id,),
                )
                draft = await cur.fetchone()
                if draft is None:
                    raise DraftNotPending(f"draft {draft_id} is not pending approval")
                cur = await conn.execute(
                    """
                    INSERT INTO erp.purchase_orders
                        (draft_id, supplier_id, material_id, quantity_kg, total_eur, approved_by)
                    SELECT %s, %s, m.material_id, %s, %s * m.unit_price_eur, %s
                    FROM erp.materials m WHERE m.material_id = %s
                    RETURNING po_id, draft_id, material_id, quantity_kg, total_eur, approved_by
                    """,
                    (
                        draft["draft_id"],
                        draft["supplier_id"],
                        draft["quantity_kg"],
                        draft["quantity_kg"],
                        approver,
                        draft["material_id"],
                    ),
                )
                return _plain(await cur.fetchone())

    async def audit(self, actor: str, action: str, decision: str, detail: dict) -> None:
        async with await psycopg.AsyncConnection.connect(self.writer_dsn) as conn:
            await conn.execute(
                "INSERT INTO audit.events (actor, action, decision, detail)"
                " VALUES (%s, %s, %s, %s)",
                (actor, action, decision, Jsonb(detail)),
            )
