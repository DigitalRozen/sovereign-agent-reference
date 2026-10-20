# ADR-0003: A separate data layer for AI access

- **Status:** Accepted
- **Date:** 2026-10-19

## Context

Connecting an agent directly to the ERP's core tables means one bug or one injected instruction is one step away from the system of record. ERP owners will not, and should not, accept that.

## Decision

Three schemas with a hard boundary, enforced by database grants:

- `erp`: core tables. No AI role has any privilege here, not even `SELECT`.
- `ai`: read-only views over the fields the agent needs, plus `ai.po_drafts`, the only table the AI layer can write. A draft is not an order.
- `audit`: append-only event log.

Database roles follow least privilege per path:

| Role | Can do | Used by |
|---|---|---|
| `ai_reader` | `SELECT` on `ai.*` views | tool server reads |
| `ai_writer` | `INSERT` drafts and audit events | tool server, agent, sandbox runner |
| `erp_integration` | change a draft's status, insert one ERP order, read material prices | the human approval path only |
| `audit_reader` | `SELECT` on the audit log | the audit page |

## Consequences

- The tests check the boundary at the database itself, independent of application code (`tests/cluster/test_data_boundaries.py`). A guard test makes sure every role can log in, so a denial can never pass just because the role could not connect.
- The views run with their owner's rights. That is what makes them a controlled window and not a grant on the base tables.
- In this repo the AI layer is a set of **views in the same database**. A real deployment would use a read replica or CDC into a separate database, so AI query load and any compromise stay off the production ERP. The grants model carries over unchanged.
