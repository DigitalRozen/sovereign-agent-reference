"""The database enforces the AI data boundary on its own, whatever the agent or LLM does."""

import pytest

pytestmark = pytest.mark.cluster


def assert_denied_by_grant(result) -> None:
    """Denied by an object-level grant, not merely unable to connect."""
    assert not result.ok
    assert "permission denied for" in result.output, result.output
    assert "permission denied for database" not in result.output, result.output


def test_seed_is_visible_through_ai_layer(psql):
    result = psql.run("ai_reader", "SELECT count(*) FROM ai.open_orders;")
    assert result.ok, result.output
    assert int(result.output) >= 3


def test_shortage_is_visible_for_the_demo_material(psql):
    sql = """
        SELECT i.available_kg - i.safety_stock_kg < sum(o.billet_kg)
        FROM ai.inventory i JOIN ai.open_orders o USING (material_id)
        WHERE i.material_id = 'BIL-6063-178'
        GROUP BY i.available_kg, i.safety_stock_kg;
    """
    result = psql.run("ai_reader", sql)
    assert result.ok, result.output
    assert result.output == "t"


@pytest.mark.parametrize("role", ["ai_reader", "ai_writer"])
def test_ai_roles_cannot_read_core_erp(psql, role):
    result = psql.run(role, "SELECT * FROM erp.inventory;")
    assert not result.ok
    assert_denied_by_grant(result)


@pytest.mark.parametrize("role", ["ai_reader", "ai_writer"])
def test_ai_roles_cannot_write_purchase_orders(psql, role):
    sql = """
        INSERT INTO erp.purchase_orders
            (supplier_id, material_id, quantity_kg, total_eur, approved_by)
        VALUES ('SUP-03', 'BIL-6082-203', 250000, 775000, 'procurement');
    """
    result = psql.run(role, sql)
    assert not result.ok
    assert_denied_by_grant(result)


def test_ai_reader_cannot_create_drafts(psql):
    sql = """
        INSERT INTO ai.po_drafts (material_id, supplier_id, quantity_kg, rationale, requested_by)
        VALUES ('BIL-6063-178', 'SUP-01', 5000, 'test', 'smoke');
    """
    result = psql.run("ai_reader", sql)
    assert not result.ok
    assert_denied_by_grant(result)


def test_ai_writer_can_create_drafts(psql):
    sql = """
        INSERT INTO ai.po_drafts (material_id, supplier_id, quantity_kg, rationale, requested_by)
        VALUES ('BIL-6063-178', 'SUP-01', 5000, 'smoke test', 'smoke')
        RETURNING status;
    """
    result = psql.run("ai_writer", sql)
    assert result.ok, result.output
    assert result.output.splitlines()[0] == "pending_approval"


def test_audit_is_append_only_even_for_superuser(psql):
    insert = psql.run(
        "ai_writer",
        "INSERT INTO audit.events (actor, action, decision) VALUES ('smoke', 'smoke', 'info');",
    )
    assert insert.ok, insert.output

    for statement in ("UPDATE audit.events SET actor = 'x';", "DELETE FROM audit.events;"):
        result = psql.run("postgres", statement)
        assert not result.ok, statement
        assert "append-only" in result.output


def test_ai_writer_cannot_read_audit_log(psql):
    result = psql.run("ai_writer", "SELECT * FROM audit.events;")
    assert not result.ok
    assert_denied_by_grant(result)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM erp.inventory;",
        "SELECT * FROM erp.sales_orders;",
        "UPDATE ai.po_drafts SET quantity_kg = 999999;",
        "DELETE FROM erp.purchase_orders;",
        "UPDATE erp.purchase_orders SET total_eur = 1;",
    ],
)
def test_erp_integration_role_can_only_do_the_approval_step(psql, statement):
    result = psql.run("erp_integration", statement)
    assert_denied_by_grant(result)


def test_ai_writer_cannot_approve_drafts(psql):
    result = psql.run("ai_writer", "UPDATE ai.po_drafts SET status = 'approved';")
    assert not result.ok
    assert_denied_by_grant(result)


@pytest.mark.parametrize("role", ["ai_reader", "ai_writer", "erp_integration"])
def test_every_application_role_can_connect(psql, role):
    """Guards the denial tests above: they only mean something if the role can log in."""
    result = psql.run(role, "SELECT current_user;")
    assert result.ok, result.output
    assert result.output == role
