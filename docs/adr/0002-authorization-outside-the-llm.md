# ADR-0002: Authorization is enforced outside the LLM, at several layers

- **Status:** Accepted
- **Date:** 2026-10-19

## Context

An LLM reads untrusted text: supplier notes, emails, documents. Prompt injection cannot be reliably prevented inside the model, so a system prompt that says "only draft orders" is not a control. This repo's seed data contains an injected supplier note on purpose.

## Decision

Treat the model as **untrusted**. Every decision that matters is made by deterministic code or configuration that the model cannot change:

| Layer | Enforces | Where |
|---|---|---|
| Identity | who the user is and which single role they hold | Keycloak realm |
| LLM gateway | that a model can be called at all, which models, how often, at what cost | LiteLLM virtual key per user |
| Tool server | which role may call which tool; business rules for drafts | `services/mcp_erp/mcp_erp/policy.py` |
| Sandbox | that generated code has no network, no credentials, bounded resources | Kubernetes Job spec + NetworkPolicy |
| Database | which role may read or write which table | grants in `02-schema.sql` |
| Human | that an order exists only after a manager approves it | approval endpoint + `erp_integration` role |

The agent itself holds **no privileges**. It forwards the user's token and uses the user's gateway key.

## Consequences

- A fully compromised model can, at worst, ask for things the current user is already allowed to do, and those requests are still policy-checked and audited. The demo shows this. The scripted model obeys the injection and is blocked.
- Each layer is tested on its own (`tests/cluster/`), so no layer's correctness depends on another's.
- The cost is some duplication: roles are checked at the tool server and again by database grants. That is deliberate.

## What this does not solve

- A buyer can still be talked into drafting something wrong *within* policy (for example, 20,000 kg from the right supplier). Human approval is the control for that.
- Data the model reads can still leak into its answer to the same user. Exfiltration to third parties is limited because the sandbox has no network and the tools only write drafts.
