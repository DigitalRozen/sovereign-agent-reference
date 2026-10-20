-- Three schemas with a hard boundary between them:
--   erp    core system of record. No AI role has any privilege here.
--   ai     the AI data layer: read-only views over erp, plus a drafts table.
--          In a real deployment this would be a replica or CDC copy, not views.
--   audit  append-only event log.

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE erp FROM PUBLIC;
GRANT CONNECT ON DATABASE erp TO ai_reader, ai_writer, erp_integration, audit_reader;

-- ---------------------------------------------------------------- erp (core)
CREATE SCHEMA erp;

CREATE TABLE erp.suppliers (
    supplier_id   text PRIMARY KEY,
    name          text NOT NULL,
    lead_time_days integer NOT NULL CHECK (lead_time_days > 0),
    notes         text NOT NULL DEFAULT ''
);

CREATE TABLE erp.materials (
    material_id   text PRIMARY KEY,
    description   text NOT NULL,
    unit          text NOT NULL CHECK (unit IN ('kg')),
    unit_price_eur numeric(10, 2) NOT NULL CHECK (unit_price_eur > 0),
    supplier_id   text NOT NULL REFERENCES erp.suppliers
);

CREATE TABLE erp.inventory (
    material_id   text PRIMARY KEY REFERENCES erp.materials,
    on_hand_kg    numeric(12, 1) NOT NULL CHECK (on_hand_kg >= 0),
    reserved_kg   numeric(12, 1) NOT NULL CHECK (reserved_kg >= 0),
    safety_stock_kg numeric(12, 1) NOT NULL CHECK (safety_stock_kg >= 0)
);

CREATE TABLE erp.sales_orders (
    order_id      text PRIMARY KEY,
    customer      text NOT NULL,
    profile_code  text NOT NULL,
    material_id   text NOT NULL REFERENCES erp.materials,
    billet_kg     numeric(12, 1) NOT NULL CHECK (billet_kg > 0),
    due_date      date NOT NULL,
    status        text NOT NULL CHECK (status IN ('open', 'in_production', 'shipped'))
);

CREATE TABLE erp.purchase_orders (
    po_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    draft_id      bigint NOT NULL UNIQUE,  -- every order traces back to one approved draft
    supplier_id   text NOT NULL REFERENCES erp.suppliers,
    material_id   text NOT NULL REFERENCES erp.materials,
    quantity_kg   numeric(12, 1) NOT NULL CHECK (quantity_kg > 0),
    total_eur     numeric(12, 2) NOT NULL CHECK (total_eur > 0),
    approved_by   text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- ai (AI data layer)
CREATE SCHEMA ai;

-- Views run with their owner's privileges, so ai_reader can read them
-- without holding any privilege on erp.*.
CREATE VIEW ai.inventory AS
SELECT i.material_id,
       m.description,
       i.on_hand_kg,
       i.reserved_kg,
       i.on_hand_kg - i.reserved_kg AS available_kg,
       i.safety_stock_kg,
       m.unit_price_eur,
       m.supplier_id
FROM erp.inventory i
JOIN erp.materials m USING (material_id);

CREATE VIEW ai.open_orders AS
SELECT order_id, customer, profile_code, material_id, billet_kg, due_date
FROM erp.sales_orders
WHERE status = 'open';

-- Supplier notes are free text from outside the company: untrusted input for the LLM.
CREATE VIEW ai.suppliers AS
SELECT supplier_id, name, lead_time_days, notes
FROM erp.suppliers;

-- The only table the AI layer can write to. A draft is not an order.
CREATE TABLE ai.po_drafts (
    draft_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    material_id   text NOT NULL,
    supplier_id   text NOT NULL,
    quantity_kg   numeric(12, 1) NOT NULL CHECK (quantity_kg > 0),
    rationale     text NOT NULL,
    requested_by  text NOT NULL,
    status        text NOT NULL DEFAULT 'pending_approval'
                  CHECK (status IN ('pending_approval', 'approved', 'rejected', 'submitted')),
    created_at    timestamptz NOT NULL DEFAULT now()
);

GRANT USAGE ON SCHEMA ai TO ai_reader, ai_writer;
GRANT SELECT ON ai.inventory, ai.open_orders, ai.suppliers TO ai_reader, ai_writer;
GRANT SELECT, INSERT ON ai.po_drafts TO ai_writer;
GRANT SELECT ON ai.po_drafts TO ai_reader;

-- The approval path: flip a draft's status and create the order. Nothing else.
GRANT USAGE ON SCHEMA ai, erp TO erp_integration;
GRANT SELECT, UPDATE (status) ON ai.po_drafts TO erp_integration;
GRANT SELECT ON erp.materials TO erp_integration;
GRANT SELECT, INSERT ON erp.purchase_orders TO erp_integration;  -- SELECT for RETURNING

-- ---------------------------------------------------------------- audit (append-only)
CREATE SCHEMA audit;

CREATE TABLE audit.events (
    event_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at   timestamptz NOT NULL DEFAULT now(),
    actor         text NOT NULL,          -- human subject (OIDC sub) or workload identity
    action        text NOT NULL,          -- e.g. tool.call, tool.denied, po.approved
    decision      text NOT NULL CHECK (decision IN ('allowed', 'denied', 'info')),
    detail        jsonb NOT NULL DEFAULT '{}'
);

CREATE FUNCTION audit.reject_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit.events is append-only';
END;
$$;

-- Blocks UPDATE/DELETE/TRUNCATE for every role, including the table owner.
-- A superuser can still disable the trigger; tamper-evidence against a DBA is out of scope.
CREATE TRIGGER events_append_only
    BEFORE UPDATE OR DELETE ON audit.events
    FOR EACH ROW EXECUTE FUNCTION audit.reject_change();
CREATE TRIGGER events_no_truncate
    BEFORE TRUNCATE ON audit.events
    FOR EACH STATEMENT EXECUTE FUNCTION audit.reject_change();

GRANT USAGE ON SCHEMA audit TO ai_writer, erp_integration, audit_reader;
GRANT INSERT ON audit.events TO ai_writer, erp_integration;
GRANT SELECT ON audit.events TO audit_reader;
