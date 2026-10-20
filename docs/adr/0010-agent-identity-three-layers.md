# ADR-0010: Agent identity as three layers

- **Status:** Accepted
- **Date:** 2026-09-06 (mapped to this implementation 2026-10-20)

## Context

The questions are always who owns an agent, what it can access, and what proof exists. Treating "agent identity" as a single IAM product fails both procurement and operations.

## Decision

Model agent identity as **three layers**, not one product, and name all three for every agent component:

1. **Human / org owner:** the accountable person or team that can shut it down.
2. **Workload / runtime identity:** how the agent and its tools authenticate to systems.
3. **Tool / data scope:** what it is allowed to read, write, spawn and spend.

## How this repo maps the layers

| Layer | In this implementation |
|---|---|
| Human owner | Every request runs as a named Keycloak user; the audit log's `actor` is that user. The deployer owns the cluster and can stop any component with `kubectl scale --replicas=0`. |
| Workload identity | Services authenticate to Postgres with separate least-privilege roles; the sandbox runner has its own Kubernetes service account limited to one namespace; the agent itself has no identity with rights of its own (ADR-0005 notes the token-exchange upgrade that would give it one). |
| Tool / data scope | Role-to-tool mapping in the MCP server; database grants per role (ADR-0003); gateway budget, RPM and model allow-list per user (ADR-0006); sandbox with no network or credentials (ADR-0007). |

## Consequences

- Vendor tools sit *under* this model; they do not replace it.
- Audit evidence maps to the layers: who (actor), with what credential (role), and within what scope (the decision and its reason).
