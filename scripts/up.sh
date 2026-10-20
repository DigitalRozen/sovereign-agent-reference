#!/usr/bin/env bash
# Create the local cluster (if needed), build images, inject runtime secrets, deploy, and wait.
set -euo pipefail

CLUSTER=sovereign-agent
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGES=(
  scripted_llm:sovereign-agent/scripted-llm:dev
  mcp_erp:sovereign-agent/mcp-erp:dev
  sandbox_runner:sovereign-agent/sandbox-runner:dev
  agent_api:sovereign-agent/agent-api:dev
)
# Base image for sandboxed runs, imported so they start without registry access.
SANDBOX_IMAGE=python:3.13.13-slim

for bin in docker k3d kubectl openssl curl; do
  command -v "$bin" >/dev/null || { echo "missing required tool: $bin" >&2; exit 1; }
done

# Optional settings (e.g. OPENROUTER_API_KEY) come from .env, which is never committed.
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

if ! k3d cluster list "$CLUSTER" >/dev/null 2>&1; then
  k3d cluster create --config "$ROOT/deploy/k3d/cluster.yaml" --wait
fi
kubectl config use-context "k3d-$CLUSTER" >/dev/null

# Application images are built locally and imported; nothing is pushed to a registry.
for entry in "${IMAGES[@]}"; do
  dir="${entry%%:*}"
  tag="${entry#*:}"
  docker build -q -t "$tag" "$ROOT/services/$dir" >/dev/null
  k3d image import -c "$CLUSTER" "$tag" >/dev/null
done
docker image inspect "$SANDBOX_IMAGE" >/dev/null 2>&1 || docker pull -q "$SANDBOX_IMAGE" >/dev/null
k3d image import -c "$CLUSTER" "$SANDBOX_IMAGE" >/dev/null

kubectl apply -f "$ROOT/deploy/base/namespaces.yaml"

# Secrets are generated on first run and live only in the cluster, never in git.
random() { openssl rand -hex "$1"; }

create_secret() {
  local name="$1"
  shift
  kubectl -n platform get secret "$name" >/dev/null 2>&1 \
    || kubectl -n platform create secret generic "$name" "$@"
}

create_secret postgres-credentials \
  --from-literal=superuser-password="$(random 24)" \
  --from-literal=ai-reader-password="$(random 24)" \
  --from-literal=ai-writer-password="$(random 24)" \
  --from-literal=litellm-password="$(random 24)" \
  --from-literal=erp-integration-password="$(random 24)" \
  --from-literal=audit-reader-password="$(random 24)"

create_secret keycloak-credentials \
  --from-literal=admin-password="$(random 16)" \
  --from-literal=agent-ui-client-secret="$(random 24)" \
  --from-literal=demo-password-alice="$(random 6)" \
  --from-literal=demo-password-morgan="$(random 6)" \
  --from-literal=demo-password-val="$(random 6)"

create_secret llm-keys \
  --from-literal=master-key="sk-$(random 24)" \
  --from-literal=user-key-alice="sk-$(random 24)" \
  --from-literal=user-key-morgan="sk-$(random 24)" \
  --from-literal=user-key-val="sk-$(random 24)"

# The provider key is the one secret that comes from the operator rather than being generated.
# The agent uses the real model only when a provider key is configured.
AGENT_MODEL=agent-default
# Passed on stdin so the key never appears in a process listing.
if [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
  AGENT_MODEL=agent-openrouter
  printf '{"stringData":{"openrouter-api-key":"%s"}}' "$OPENROUTER_API_KEY" \
    | kubectl -n platform patch secret llm-keys --type merge --patch-file=/dev/stdin >/dev/null
  # Pick up a key added after the first deploy.
  kubectl -n platform rollout restart deployment/litellm >/dev/null 2>&1 || true
fi

# Jobs are immutable; re-run the (idempotent) key bootstrap on every deploy.
kubectl -n platform delete job llm-key-bootstrap --ignore-not-found >/dev/null
kubectl apply -k "$ROOT/deploy/base"
kubectl -n platform set env deployment/agent-api AGENT_MODEL="$AGENT_MODEL" >/dev/null

kubectl -n platform rollout status statefulset/postgres --timeout=180s
kubectl -n platform rollout status deployment/keycloak --timeout=300s
kubectl -n platform rollout status deployment/scripted-llm --timeout=120s
kubectl -n platform rollout status deployment/mcp-erp --timeout=120s
kubectl -n platform rollout status deployment/sandbox-runner --timeout=120s
kubectl -n platform rollout status deployment/agent-api --timeout=120s
kubectl -n platform rollout status deployment/litellm --timeout=600s
kubectl -n platform wait --for=condition=complete job/llm-key-bootstrap --timeout=300s

# Traefik is installed by k3s asynchronously; wait until the public URL answers.
for _ in $(seq 60); do
  curl -fs -o /dev/null http://localhost:8080/auth/realms/tarnwick && break
  sleep 2
done
curl -fsS -o /dev/null http://localhost:8080/auth/realms/tarnwick \
  || { echo "Keycloak is not reachable on http://localhost:8080/auth" >&2; exit 1; }

echo "Cluster is up. Agent UI: http://localhost:8080/agent/  (model: $AGENT_MODEL)"
echo "Run 'make smoke' to verify, 'make creds' for demo logins, 'make demo' for the scenario."
