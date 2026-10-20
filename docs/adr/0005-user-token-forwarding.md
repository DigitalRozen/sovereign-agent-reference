# ADR-0005: Forward the user's token now; token exchange later

- **Status:** Accepted (with a known limitation)
- **Date:** 2026-10-19

## Context

Downstream services (the tool server and the sandbox) must authorize the **human** on whose behalf the agent acts, not the agent. Two standard ways exist:

1. Forward the user's access token, with every downstream service listed in its audience.
2. OAuth 2.0 Token Exchange (RFC 8693): the agent exchanges the user's token for a narrower one per downstream service, ideally with an `act` claim naming the agent.

## Decision

Forward the user's token for now. The `agent-ui` client adds the audiences `mcp-erp` and `sandbox-runner` through audience mappers. Each service verifies signature, issuer, its own audience and expiry, and maps realm roles itself.

## Consequences

- Simple, standard and easy to test. Every service sees the real user and role.
- **Limitation:** one token is valid at both downstream services, and nothing in it says an agent is involved. A leaked token is usable at either service until it expires (5-minute lifespan).
- The upgrade path is token exchange, with one audience per exchanged token and an `act` claim for the agent's workload identity. That needs Keycloak's token-exchange configuration and a confidential client for the agent. It is listed as a stretch goal.
