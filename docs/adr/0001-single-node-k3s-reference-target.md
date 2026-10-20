# ADR-0001: Single-node k3s (via k3d) as the reference target

- **Status:** Accepted
- **Date:** 2026-10-19

## Context

The architecture has to run on the kind of infrastructure a customer controls, and a reviewer has to be able to run it on a laptop with one command. It also has to run in CI on every push, otherwise "runs on Kubernetes" is a claim, not a fact.

## Decision

Target **k3s**, created locally with **k3d** (k3s in Docker), as a single node. All components are plain Kubernetes manifests applied with kustomize. CI creates a fresh cluster and runs the same `make up && make smoke` a reviewer runs.

k3s rather than kind, because the sandbox depends on NetworkPolicy being enforced. k3s ships a NetworkPolicy controller. kind's default CNI does not enforce policies, so the deny-all policy would silently do nothing.

## Consequences

- One command creates the whole stack: identity, gateway, tools, sandbox, agent, data.
- Anything that works here is standard Kubernetes. Moving to k3s or RKE2 on customer hardware, or to a managed cluster, is a deployment change, not a redesign.
- There is no high availability. Every service has one replica, and some keep state in memory (see the README limitations).
- Images are built locally and imported into the cluster. There is no registry and no image signing.

## Alternatives considered

- **kind:** NetworkPolicy is not enforced by default, which would make the sandbox isolation fake.
- **Docker Compose:** easier to start, but it proves nothing about Kubernetes RBAC, Pod Security or NetworkPolicy.
- **Helm chart:** worth having for real installs. It is a stretch goal; plain manifests are easier to read in a review.
