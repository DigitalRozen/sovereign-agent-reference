"""Authorization and business rules. Plain code, evaluated outside the LLM."""

from dataclasses import dataclass

from .auth import Caller

# Which roles may call which tool. Anything not listed is denied.
TOOL_ROLES: dict[str, frozenset[str]] = {
    "get_inventory": frozenset({"buyer", "procurement_manager", "viewer"}),
    "get_open_orders": frozenset({"buyer", "procurement_manager", "viewer"}),
    "get_suppliers": frozenset({"buyer", "procurement_manager", "viewer"}),
    "draft_po": frozenset({"buyer"}),
}

APPROVER_ROLE = "procurement_manager"

# A single draft above this is rejected outright, whatever the model or the data says.
MAX_DRAFT_KG = 20_000


class PolicyDenied(Exception):
    """A request that is well-formed but not allowed."""


def authorize_tool(caller: Caller, tool: str) -> None:
    allowed = TOOL_ROLES.get(tool, frozenset())
    if not caller.roles & allowed:
        raise PolicyDenied(f"role(s) {sorted(caller.roles) or ['none']} may not call {tool}")


@dataclass(frozen=True)
class DraftRequest:
    material_id: str
    supplier_id: str
    quantity_kg: float
    rationale: str


def check_draft(request: DraftRequest, registered_supplier_id: str | None) -> None:
    if registered_supplier_id is None:
        raise PolicyDenied(f"unknown material {request.material_id}")
    if request.supplier_id != registered_supplier_id:
        raise PolicyDenied(
            f"{request.material_id} is sourced from {registered_supplier_id}, "
            f"not {request.supplier_id}"
        )
    if not 0 < request.quantity_kg <= MAX_DRAFT_KG:
        raise PolicyDenied(
            f"quantity {request.quantity_kg:g} kg is outside the allowed range "
            f"(0, {MAX_DRAFT_KG}] kg per draft"
        )
    if not request.rationale.strip():
        raise PolicyDenied("a draft needs a rationale")


def check_approval(caller: Caller, requested_by: str) -> None:
    if APPROVER_ROLE not in caller.roles:
        raise PolicyDenied(f"approving requires the {APPROVER_ROLE} role")
    if caller.username == requested_by:
        raise PolicyDenied("the requester of a draft cannot approve it")
