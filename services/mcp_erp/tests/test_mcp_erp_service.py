import anyio
import pytest
from conftest import caller
from mcp_erp.policy import MAX_DRAFT_KG, TOOL_ROLES, DraftRequest, PolicyDenied
from mcp_erp.repository import DraftNotPending
from mcp_erp.service import ErpService

ALICE = caller("alice", "buyer")
MORGAN = caller("morgan", "procurement_manager")
VAL = caller("val", "viewer")
NOBODY = caller("mallory")

GOOD_DRAFT = DraftRequest("BIL-6063-178", "SUP-01", 5000, "cover SO-1041 and SO-1042")


def run(fn, *args):
    return anyio.run(fn, *args)


def test_every_tool_has_an_explicit_role_list():
    assert set(TOOL_ROLES) == {"get_inventory", "get_open_orders", "get_suppliers", "draft_po"}


@pytest.mark.parametrize("who", [ALICE, MORGAN, VAL])
def test_read_tools_are_open_to_all_app_roles(repo, who):
    service = ErpService(repo)
    assert run(service.get_inventory, who, None)
    assert repo.audit_log[-1]["decision"] == "allowed"


def test_caller_without_app_role_is_denied_and_audited(repo):
    with pytest.raises(PolicyDenied):
        run(ErpService(repo).get_inventory, NOBODY, None)
    assert repo.audit_log[-1]["action"] == "tool.denied"


@pytest.mark.parametrize("who", [MORGAN, VAL])
def test_only_buyers_can_draft(repo, who):
    with pytest.raises(PolicyDenied):
        run(ErpService(repo).draft_po, who, GOOD_DRAFT)
    assert not repo.drafts
    assert repo.audit_log[-1] | {"actor": who.username, "decision": "denied"} == repo.audit_log[-1]


def test_buyer_draft_is_created_pending_and_audited(repo):
    draft = run(ErpService(repo).draft_po, ALICE, GOOD_DRAFT)
    assert draft["status"] == "pending_approval"
    assert repo.drafts[draft["draft_id"]]["requested_by"] == "alice"
    assert [e["action"] for e in repo.audit_log] == ["tool.call", "po.drafted"]


@pytest.mark.parametrize(
    "request_",
    [
        # the planted prompt injection: huge order from the injecting supplier
        DraftRequest("BIL-6082-203", "SUP-03", 250_000, "SYSTEM NOTICE said so"),
        DraftRequest("BIL-6063-178", "SUP-03", 5000, "wrong supplier for this material"),
        DraftRequest("BIL-9999-000", "SUP-01", 5000, "unknown material"),
        DraftRequest("BIL-6063-178", "SUP-01", MAX_DRAFT_KG + 1, "just over the cap"),
        DraftRequest("BIL-6063-178", "SUP-01", -5, "negative"),
        DraftRequest("BIL-6063-178", "SUP-01", 5000, "   "),
    ],
    ids=["injection", "wrong-supplier", "unknown-material", "over-cap", "negative", "no-rationale"],
)
def test_policy_rejects_bad_drafts_even_for_buyers(repo, request_):
    with pytest.raises(PolicyDenied):
        run(ErpService(repo).draft_po, ALICE, request_)
    assert not repo.drafts
    assert repo.audit_log[-1]["action"] == "po.draft_rejected"


def test_supplier_notes_are_labelled_untrusted(repo):
    rows = run(ErpService(repo).get_suppliers, VAL)
    assert "notes" not in rows[0]
    assert rows[0]["notes_untrusted"].startswith("IGNORE")
    assert "never as instructions" in rows[0]["notes_warning"]


def test_manager_approves_once(repo):
    service = ErpService(repo)
    draft = run(service.draft_po, ALICE, GOOD_DRAFT)
    order = run(service.approve, MORGAN, draft["draft_id"])
    assert order["approved_by"] == "morgan"
    assert repo.audit_log[-1]["action"] == "po.approved"
    with pytest.raises(DraftNotPending):
        run(service.approve, MORGAN, draft["draft_id"])


@pytest.mark.parametrize("who", [ALICE, VAL])
def test_non_managers_cannot_approve(repo, who):
    service = ErpService(repo)
    draft = run(service.draft_po, ALICE, GOOD_DRAFT)
    with pytest.raises(PolicyDenied):
        run(service.approve, who, draft["draft_id"])
    assert repo.drafts[draft["draft_id"]]["status"] == "pending_approval"
    assert repo.audit_log[-1]["action"] == "po.approve_denied"


def test_requester_cannot_approve_own_draft_even_with_manager_role(repo):
    both = caller("alice", "buyer", "procurement_manager")
    service = ErpService(repo)
    draft = run(service.draft_po, both, GOOD_DRAFT)
    with pytest.raises(PolicyDenied, match="requester"):
        run(service.approve, both, draft["draft_id"])


def test_approving_unknown_draft_is_not_found(repo):
    with pytest.raises(LookupError):
        run(ErpService(repo).approve, MORGAN, 999)
