"""The ERP tool server with real tokens, the real database and the real audit log."""

import json
import uuid
from collections.abc import Iterator

import anyio
import httpx
import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .conftest import port_forward

pytestmark = pytest.mark.cluster


@pytest.fixture(scope="module")
def mcp_url() -> Iterator[str]:
    with port_forward("mcp-erp", 18000, 8000) as url:
        yield url


def call_tool(base_url: str, token: str, tool: str, args: dict | None = None):
    async def _call():
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
            async with streamable_http_client(f"{base_url}/mcp", http_client=http) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    return await session.call_tool(tool, args or {})

    return anyio.run(_call)


def draft_args(**overrides) -> dict:
    # A unique rationale lets each test find its own rows in the shared audit log.
    return {
        "material_id": "BIL-6063-178",
        "supplier_id": "SUP-01",
        "quantity_kg": 5000,
        "rationale": f"smoke {uuid.uuid4().hex[:8]}",
        **overrides,
    }


def approve(base_url: str, token: str, draft_id: int) -> httpx.Response:
    return httpx.post(
        f"{base_url}/approvals/{draft_id}", headers={"Authorization": f"Bearer {token}"}, timeout=10
    )


def test_viewer_can_read_inventory(mcp_url, user_token):
    result = call_tool(mcp_url, user_token("val"), "get_inventory", {"material_id": "BIL-6063-178"})
    assert not result.is_error, result.content
    # List results arrive as structured content; dict results as one JSON text block.
    rows = result.structured_content["result"]
    assert [row["material_id"] for row in rows] == ["BIL-6063-178"]


def test_viewer_cannot_draft_and_the_denial_is_audited(mcp_url, user_token, psql):
    args = draft_args()
    result = call_tool(mcp_url, user_token("val"), "draft_po", args)
    assert result.is_error
    assert "denied by policy" in result.content[0].text

    audit = psql.run(
        "postgres",
        "SELECT actor, decision FROM audit.events "
        "WHERE action = 'tool.denied' AND actor = 'val' AND detail->>'tool' = 'draft_po' "
        "ORDER BY event_id DESC LIMIT 1;",
    )
    assert audit.output == "val|denied"


def test_injected_order_is_rejected_by_policy_not_by_the_model(mcp_url, user_token, psql):
    """What the planted supplier note asks for, sent directly as a buyer."""
    args = draft_args(material_id="BIL-6082-203", supplier_id="SUP-03", quantity_kg=250000)
    result = call_tool(mcp_url, user_token("alice"), "draft_po", args)
    assert result.is_error
    assert "outside the allowed range" in result.content[0].text

    drafts = psql.run(
        "postgres", f"SELECT count(*) FROM ai.po_drafts WHERE rationale = '{args['rationale']}';"
    )
    assert drafts.output == "0"


def test_draft_then_human_approval_creates_exactly_one_erp_order(mcp_url, user_token, psql):
    args = draft_args()
    result = call_tool(mcp_url, user_token("alice"), "draft_po", args)
    assert not result.is_error, result.content
    draft = json.loads(result.content[0].text)
    assert draft["status"] == "pending_approval"

    assert approve(mcp_url, user_token("alice"), draft["draft_id"]).status_code == 403
    assert approve(mcp_url, user_token("val"), draft["draft_id"]).status_code == 403

    approved = approve(mcp_url, user_token("morgan"), draft["draft_id"])
    assert approved.status_code == 200, approved.text
    assert approved.json()["approved_by"] == "morgan"
    assert approve(mcp_url, user_token("morgan"), draft["draft_id"]).status_code == 409

    orders = psql.run(
        "postgres",
        "SELECT count(*), max(approved_by), max(total_eur) FROM erp.purchase_orders "
        f"WHERE draft_id = {draft['draft_id']};",
    )
    assert orders.output == "1|morgan|14250.00"  # 5000 kg x 2.85 EUR/kg

    trail = psql.run(
        "postgres",
        "SELECT string_agg(actor || ':' || action, ',' ORDER BY event_id) FROM audit.events "
        f"WHERE detail->>'draft_id' = '{draft['draft_id']}';",
    )
    assert trail.output.split(",") == [
        "alice:po.drafted",
        "alice:po.approve_denied",
        "val:po.approve_denied",
        "morgan:po.approved",
    ]


def test_requests_without_a_valid_token_never_reach_a_tool(mcp_url):
    headers = {"Accept": "application/json, text/event-stream", "Authorization": "Bearer forged"}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    assert httpx.post(f"{mcp_url}/mcp", json=body, headers=headers).status_code == 401
    assert approve(mcp_url, "forged", 1).status_code == 401
