# ADR-0009: Append-only audit log in Postgres

- **Status:** Accepted
- **Date:** 2026-10-19

## Context

After an incident, or in a customer review, the question is "who asked for what, what did the system allow or refuse, and why". The answer has to come from the system, not from the model's own account of what it did.

## Decision

A single `audit.events` table. Writers can only `INSERT`. A trigger rejects `UPDATE`, `DELETE` and `TRUNCATE` for every role, including the table owner. Events carry the human actor (the OIDC username), an action, a decision (`allowed`, `denied` or `info`), and a JSON detail.

Writers: the tool server (`tool.call`, `tool.denied`, `po.drafted`, `po.draft_rejected`, `po.approved`, `po.approve_denied`), the sandbox (`sandbox.run`, `sandbox.denied`) and the agent (`agent.request`, `agent.answer`). Readers: the `audit_reader` role behind the UI's audit page.

## Consequences

- One query reconstructs a run end to end. The e2e test checks that the trail of a scenario run is complete.
- Writers cannot read the log, so a compromised writer cannot learn what is being watched.

## What this does not give

- **Tamper evidence against a database superuser.** A superuser can disable the trigger. For that you need hash-chained events, or shipping events to write-once storage or a SIEM outside the database's trust domain. Both are natural next steps.
- Retention and PII handling are not designed. The audit log stores questions verbatim (truncated to 500 characters).
