"""The real app over real HTTP: MCP protocol, bearer auth, Host checks. Fake database only."""

import json
import socket
import threading
import time

import anyio
import httpx2
import pytest
import uvicorn
from conftest import FakeRepository
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp_erp import server
from mcp_erp.policy import TOOL_ROLES

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
GOOD_DRAFT = {
    "material_id": "BIL-6063-178",
    "supplier_id": "SUP-01",
    "quantity_kg": 5000,
    "rationale": "cover SO-1041",
}


@pytest.fixture(scope="module")
def live_server(signing_key):
    """One server per test module: the app's MCP session manager can only start once."""
    public_key = signing_key.public_key()
    original = server.verifier._resolve_key, server.service.repo
    server.verifier._resolve_key = lambda _token: public_key
    server.service.repo = FakeRepository()

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    uv = uvicorn.Server(
        uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not uv.started:
        assert thread.is_alive() and time.monotonic() < deadline, "server failed to start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    uv.should_exit = True
    thread.join(timeout=5)
    server.verifier._resolve_key, server.service.repo = original


def call_tool(base_url: str, token: str, tool: str, args: dict | None = None):
    async def _call():
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx2.AsyncClient(headers=headers, timeout=10) as http:
            async with streamable_http_client(f"{base_url}/mcp", http_client=http) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    return await session.call_tool(tool, args or {})

    return anyio.run(_call)


def test_model_facing_tools_match_policy_and_include_no_way_to_place_orders():
    tools = {tool.name for tool in anyio.run(server.mcp.list_tools)}
    assert tools == set(TOOL_ROLES)
    assert not {t for t in tools if any(w in t for w in ("submit", "approve", "order_create"))}


def test_mcp_endpoint_requires_a_bearer_token(live_server):
    response = httpx2.post(f"{live_server}/mcp", json=LIST_TOOLS, headers=MCP_HEADERS)
    assert response.status_code == 401


def test_mcp_endpoint_rejects_a_forged_token(live_server, make_token):
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {make_token()}x"}
    response = httpx2.post(f"{live_server}/mcp", json=LIST_TOOLS, headers=headers)
    assert response.status_code == 401


def test_approval_endpoint_requires_a_valid_bearer_token(live_server):
    assert httpx2.post(f"{live_server}/approvals/1").status_code == 401
    junk = {"Authorization": "Bearer junk"}
    assert httpx2.post(f"{live_server}/approvals/1", headers=junk).status_code == 401


def test_unexpected_host_header_is_rejected(live_server, make_token):
    headers = {**MCP_HEADERS, "Host": "attacker.test", "Authorization": f"Bearer {make_token()}"}
    response = httpx2.post(f"{live_server}/mcp", json=LIST_TOOLS, headers=headers)
    assert response.status_code in (400, 421)


def test_buyer_drafts_over_mcp_then_manager_approves_over_http(live_server, make_token):
    result = call_tool(live_server, make_token("alice", roles=("buyer",)), "draft_po", GOOD_DRAFT)
    assert not result.is_error, result.content
    draft = json.loads(result.content[0].text)
    assert draft["status"] == "pending_approval"

    url = f"{live_server}/approvals/{draft['draft_id']}"
    as_alice = {"Authorization": f"Bearer {make_token('alice', roles=('buyer',))}"}
    as_morgan = {"Authorization": f"Bearer {make_token('morgan', roles=('procurement_manager',))}"}
    assert httpx2.post(url, headers=as_alice).status_code == 403
    approved = httpx2.post(url, headers=as_morgan)
    assert approved.status_code == 200, approved.text
    assert approved.json()["approved_by"] == "morgan"
    assert httpx2.post(url, headers=as_morgan).status_code == 409


def test_policy_denial_reaches_the_model_as_an_error_result(live_server, make_token):
    result = call_tool(live_server, make_token("val", roles=("viewer",)), "draft_po", GOOD_DRAFT)
    assert result.is_error
    assert "denied by policy" in result.content[0].text


def test_list_results_arrive_as_structured_content(live_server, make_token):
    result = call_tool(live_server, make_token("val", roles=("viewer",)), "get_inventory")
    assert not result.is_error, result.content
    assert result.structured_content["result"][0]["material_id"] == "BIL-6063-178"
