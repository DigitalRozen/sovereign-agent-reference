#!/usr/bin/env bash
# Check that NetworkPolicy is actually enforced: start one short-lived pod in the sandbox
# namespace (where deny-all applies) and try to reach the Kubernetes API service.
# Exit 0: blocked (enforced). Exit 1: reachable (NOT enforced). Exit 2: inconclusive.
# With --trace it tries every 2 s from the moment the pod starts and prints each result,
# which tells a policy that is applied late apart from one that is never applied.
set -uo pipefail

TRACE=false
[[ "${1:-}" == --trace ]] && TRACE=true

NS=sandbox
POD="netpol-probe-$(date +%s)"
IMAGE=python:3.13.13-slim

# shellcheck disable=SC2329  # called by the EXIT trap
cleanup() { kubectl -n "$NS" delete pod "$POD" --ignore-not-found --wait=false >/dev/null 2>&1; }
trap cleanup EXIT

# Same hardening as a sandbox run, so the namespace's restricted Pod Security admits it.
# The sleep gives the policy controller time to see the new pod before it connects.
kubectl -n "$NS" create -f - >/dev/null <<EOF || exit 2
apiVersion: v1
kind: Pod
metadata:
  name: $POD
  labels: { role: netpol-probe }
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  enableServiceLinks: false
  securityContext:
    runAsNonRoot: true
    runAsUser: 65532
    runAsGroup: 65532
    seccompProfile: { type: RuntimeDefault }
  containers:
    - name: probe
      image: $IMAGE
      imagePullPolicy: IfNotPresent
      command:
        - python
        - -I
        - -c
        - |
          import socket, sys, time
          def attempt():
              try:
                  socket.create_connection(("10.43.0.1", 443), timeout=1).close()
                  return "reachable"
              except OSError as exc:
                  return "blocked " + type(exc).__name__
          if sys.argv[1] == "trace":
              start = time.monotonic()
              for _ in range(15):
                  print(f"t+{time.monotonic() - start:4.1f}s {attempt()}", flush=True)
                  time.sleep(2)
          else:
              time.sleep(5)
              print(attempt())
        - $([[ $TRACE == true ]] && echo trace || echo once)
      resources:
        requests: { cpu: 50m, memory: 32Mi }
        limits: { cpu: 200m, memory: 64Mi }
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities: { drop: [ALL] }
EOF

for _ in $(seq 90); do
  phase="$(kubectl -n "$NS" get pod "$POD" -o jsonpath='{.status.phase}' 2>/dev/null)"
  [[ "$phase" == Succeeded || "$phase" == Failed ]] && break
  sleep 1
done

result="$(kubectl -n "$NS" logs "$POD" 2>/dev/null)"
if $TRACE; then
  echo "$result"
  exit 0
fi
case "$result" in
  reachable*) exit 1 ;;
  blocked*) exit 0 ;;
  *) exit 2 ;;
esac
