# ADR-0006: LiteLLM as the LLM gateway, with one virtual key per user

- **Status:** Accepted
- **Date:** 2026-10-19

## Context

On customer infrastructure, model access needs the same governance as any other shared resource: who may call which model, how much they may spend, how fast, and a record of it. It must also be possible to swap providers, or run fully offline, without touching the agent.

## Decision

All model traffic goes through **LiteLLM** (pinned by image digest, because the gateway sees every prompt and holds provider keys). It is cluster-internal, with no Ingress.

- One **virtual key per user**, created at deploy time with a budget, a budget period, an RPM limit and a model allow-list. The agent uses the key of the user it is acting for, so spend is attributed to a person and a cost center.
- Two models behind stable names: `agent-default`, a deterministic local model (`scripted-llm`) used by CI and keyless demos, and `agent-openrouter`, a real model used when `OPENROUTER_API_KEY` is set. Swapping providers is a gateway config change.

## Consequences

- Tests prove the gateway's behaviour itself: 401 without a key, model allow-lists, 429 on the rate limit, a blocked call once a budget is spent, and spend recorded per key.
- The stack runs with no outbound network at all when no provider key is set. That matters for sovereign or on-prem deployments.
- Keys are bearer secrets stored in a Kubernetes Secret. Binding the gateway to the user's OIDC token instead (JWT auth) would remove the key mapping, but it needs LiteLLM features beyond the open-source baseline. Revisit when needed.

## Alternatives considered

- **Envoy AI Gateway or Kong:** strong traffic control, but cost attribution and per-user budgets need more glue.
- **Building one:** the budget and spend logic is where the edge cases are. Not worth owning for this scope.
