#!/usr/bin/env bash
# Set the spend of the demo users' gateway keys back to zero. The budgets are small on
# purpose (val: USD 0.05 per 30 days), so on a cluster that is kept between runs a few
# rounds of `make smoke` used them up and the gateway refused the agent's model calls.
# make smoke and make reset-demo run this; budgets and rate limits are not changed.
set -euo pipefail

NS=platform
PORT=14001

secret() { kubectl -n "$NS" get secret llm-keys -o jsonpath="{.data.$1}" | base64 -d; }

kubectl -n "$NS" port-forward svc/litellm "$PORT:4000" >/dev/null 2>&1 &
pf=$!
# shellcheck disable=SC2329  # called by the EXIT trap
cleanup() { kill "$pf" 2>/dev/null || true; }
trap cleanup EXIT
for _ in $(seq 100); do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/health/liveliness" && break
  sleep 0.2
done

master="$(secret master-key)"
for user in alice morgan val; do
  key="$(secret "user-key-$user")"
  # Keys go to curl on stdin (-K -), so they never appear in a process listing.
  printf 'url = "http://127.0.0.1:%s/key/%s/reset_spend"\nheader = "Authorization: Bearer %s"\n' \
    "$PORT" "$key" "$master" |
    curl -fsS --retry 5 --retry-all-errors --retry-delay 2 -o /dev/null -K - \
      -H 'Content-Type: application/json' -d '{"reset_to": 0}'
done
echo "Gateway spend reset to 0 for alice, morgan and val."
