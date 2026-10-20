# ADR-0008: MCP over streamable HTTP as the tool boundary

- **Status:** Accepted
- **Date:** 2026-10-19

## Context

Tools are where an agent touches enterprise systems. The boundary should be a network service with its own authentication and authorization, reusable by any agent or model vendor. It should not be a library inside the agent process, where a bug or an injection inherits all of the process's rights.

## Decision

The ERP tools are an **MCP server** (`services/mcp_erp`, MCP Python SDK 2.3) over streamable HTTP:

- Bearer-token auth through the SDK's `TokenVerifier`. The server verifies the end user's Keycloak token itself.
- A role list for every tool in `policy.py`. Anything not listed is denied.
- Deterministic business rules for drafts: the registered supplier only, a per-draft quantity cap, a rationale required.
- Every call, allowed or denied, is written to the audit log. Supplier notes are returned under `notes_untrusted` with a warning field.
- Host-header (DNS rebinding) protection limited to the service's cluster names.

## Consequences

- Any MCP-capable client can use the same tools with the same guarantees, including other agents and IDE assistants.
- Policy denials reach the model as normal tool errors (`is_error`), so a well-behaved model can recover. A misbehaving one is still stopped.
- The SDK's 2.x API differs from 1.x (`FastMCP` became `MCPServer`). The version is pinned exactly.
