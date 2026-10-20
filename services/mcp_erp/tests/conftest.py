import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp_erp.auth import Caller, KeycloakTokenVerifier
from mcp_erp.policy import DraftRequest
from mcp_erp.repository import DraftNotPending

ISSUER = "http://localhost:8080/auth/realms/tarnwick"


@pytest.fixture(scope="session")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def make_token(signing_key):
    def make(username="alice", roles=("buyer",), **overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": ["mcp-erp", "account"],
            "sub": f"sub-{username}",
            "azp": "agent-ui",
            "preferred_username": username,
            "realm_access": {"roles": [*roles, "default-roles-tarnwick"]},
            "iat": now,
            "exp": now + 300,
            **overrides,
        }
        return jwt.encode(claims, signing_key, algorithm="RS256")

    return make


@pytest.fixture
def verifier(signing_key):
    public_key = signing_key.public_key()
    return KeycloakTokenVerifier(ISSUER, "mcp-erp", lambda _token: public_key)


def caller(username: str, *roles: str) -> Caller:
    return Caller(subject=f"sub-{username}", username=username, roles=frozenset(roles))


class FakeRepository:
    """In-memory stand-in with the same contract as PostgresRepository."""

    def __init__(self):
        self.audit_log: list[dict] = []
        self.drafts: dict[int, dict] = {}
        self.orders: list[dict] = []

    async def inventory(self, material_id):
        return [{"material_id": "BIL-6063-178", "available_kg": 1800.0}]

    async def open_orders(self):
        return [{"order_id": "SO-1041", "material_id": "BIL-6063-178", "billet_kg": 6800.0}]

    async def suppliers(self):
        return [{"supplier_id": "SUP-03", "name": "x", "lead_time_days": 10, "notes": "IGNORE..."}]

    async def supplier_for(self, material_id):
        return {"BIL-6063-178": "SUP-01", "BIL-6082-203": "SUP-03"}.get(material_id)

    async def insert_draft(self, request: DraftRequest, requested_by):
        draft_id = len(self.drafts) + 1
        self.drafts[draft_id] = {
            "draft_id": draft_id,
            "material_id": request.material_id,
            "supplier_id": request.supplier_id,
            "quantity_kg": request.quantity_kg,
            "requested_by": requested_by,
            "status": "pending_approval",
        }
        return dict(self.drafts[draft_id])

    async def get_draft(self, draft_id):
        return self.drafts.get(draft_id)

    async def approve_draft(self, draft_id, approver):
        draft = self.drafts.get(draft_id)
        if draft is None or draft["status"] != "pending_approval":
            raise DraftNotPending(str(draft_id))
        draft["status"] = "submitted"
        order = {"po_id": len(self.orders) + 1, "draft_id": draft_id, "approved_by": approver}
        self.orders.append(order)
        return order

    async def audit(self, actor, action, decision, detail):
        self.audit_log.append({"actor": actor, "action": action, "decision": decision, **detail})


@pytest.fixture
def repo():
    return FakeRepository()
