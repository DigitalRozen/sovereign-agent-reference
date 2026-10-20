# ADR-0007: Sandbox = ephemeral Kubernetes Job + deny-all NetworkPolicy (not gVisor yet)

- **Status:** Accepted
- **Date:** 2026-10-19

## Context

The agent needs to run code the model wrote: arithmetic, small data transformations. That code is untrusted by definition. It must not reach the network or the cluster, must not see credentials, and must not be able to exhaust the node.

## Decision

Each run is a one-shot **Kubernetes Job** in the `sandbox` namespace, created by `sandbox-runner`:

- **Namespace:** Pod Security `restricted` is enforced, a NetworkPolicy denies all ingress and egress (including DNS), and a ResourceQuota caps Jobs, pods, CPU and memory.
- **Pod:** no service account token, no service links, no host namespaces; non-root; read-only root filesystem; all capabilities dropped; `RuntimeDefault` seccomp; `python -I`.
- **Limits:** 500m CPU, 128 MiB memory, 16 MiB `/tmp`, a 15-second deadline, no retries, garbage-collected after 5 minutes.
- **Runner:** verifies the user's token (`sandbox-runner` audience; buyer or manager only). Its RBAC is limited to Jobs and pod logs in that one namespace. Every run is audited with the code's SHA-256.

## Consequences

- Cluster tests run hostile code: network probes against the internet, cluster DNS and the kube API; credential and filesystem checks; an infinite loop; a memory bomb (`tests/cluster/test_sandbox.py`).
- Start-up latency is a few seconds per run. That is acceptable for an agent step, but not for interactive notebooks.

## What this does not give

- **Kernel isolation.** The code shares the node's kernel. A container escape reaches the node. The next step is a `RuntimeClass` with gVisor or Kata Containers, which changes one field in the Job spec. It is listed as a stretch goal, because nested virtualization on WSL2 is unreliable.
- Output is size-capped but not content-filtered.
