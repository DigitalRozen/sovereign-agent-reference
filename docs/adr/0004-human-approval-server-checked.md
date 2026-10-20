# ADR-0004: Human approval is a separate, server-checked step, not a tool

- **Status:** Accepted
- **Date:** 2026-10-19

## Context

"Human in the loop" often means the agent asks "shall I proceed?" and then calls the same tool either way. If the model can reach the action, the approval is advisory.

## Decision

- The model-facing tool list contains **no tool that creates an order**. A test asserts this.
- Approval is a plain HTTP endpoint (`POST /approvals/{draft_id}`) on the ERP server. It verifies the caller's **own** access token, requires the `procurement_manager` role, and rejects approval by the person who requested the draft.
- Approval writes through a dedicated `erp_integration` database role, in one transaction that moves the draft from `pending_approval` to `submitted` and inserts exactly one order (`draft_id` is unique).
- Every approval and every refused approval is audited.

## Consequences

- An injected instruction such as "mark it approved by procurement" has nothing to call.
- Separation of duties holds even for a user who has both roles.
- The approval UI is part of the agent web app for convenience, but it is only a client. The decision is made by the ERP server.

## Limitations

- The endpoint runs in the same process as the MCP tools. A stricter design puts it in its own service with its own credentials, so a bug in tool handling cannot reach it.
- There is no step-up authentication (for example, MFA at approval time) and no amount-based approval chain. Both would be policy additions at the same endpoint.
- A Telegram approval channel was planned as a stretch goal and is not built.
