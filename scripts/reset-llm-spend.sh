#!/usr/bin/env bash
# Set the spend of the demo users' gateway keys back to zero. The budgets are small on
# purpose (val: USD 0.05 per 30 days), so on a cluster that is kept between runs a few
# rounds of `make smoke` used them up and the gateway refused the agent's model calls.
# make smoke and make reset-demo run this; budgets and rate limits are not changed.
#
# Only keys that have used at least half their budget are reset. LiteLLM checks budgets
# against an in-memory spend counter that keeps the old value for up to 10 minutes, so
# after a reset the gateway is restarted and its new pod reads spend from the database.
set -euo pipefail

NS=platform
PORT=14001
BASE="http://127.0.0.1:$PORT"

secret() { kubectl -n "$NS" get secret llm-keys -o jsonpath="{.data.$1}" | base64 -d; }

kubectl -n "$NS" port-forward svc/litellm "$PORT:4000" >/dev/null 2>&1 &
pf=$!
# shellcheck disable=SC2329  # called by the EXIT trap
cleanup() { kill "$pf" 2>/dev/null || true; }
trap cleanup EXIT
for _ in $(seq 100); do
  curl -s -o /dev/null "$BASE/health/liveliness" && break
  sleep 0.2
done

# Keys go to curl on stdin (-K -), so they never appear in a process listing.
admin() { # admin <path> [curl args...]
  local path="$1"
  shift
  printf 'url = "%s%s"\nheader = "Authorization: Bearer %s"\n' "$BASE" "$path" "$master" |
    curl -fsS --retry 5 --retry-all-errors --retry-delay 2 -K - "$@"
}

master="$(secret master-key)"
reset=()
for user in alice morgan val; do
  key="$(secret "user-key-$user")"
  info="$(admin "/key/info?key=$key")"
  if python3 -c 'import json,sys; i=json.load(sys.stdin)["info"]; b=i.get("max_budget"); sys.exit(0 if b and (i.get("spend") or 0) >= b / 2 else 1)' <<<"$info"; then
    admin "/key/$key/reset_spend" -o /dev/null -H 'Content-Type: application/json' -d '{"reset_to": 0}'
    reset+=("$user")
  fi
done

if ((${#reset[@]} == 0)); then
  echo "Gateway budgets: every demo user has more than half left; nothing reset."
  exit 0
fi
echo "Gateway spend reset to 0 for ${reset[*]}; restarting the gateway so it counts."
kubectl -n "$NS" rollout restart deployment/litellm >/dev/null
kubectl -n "$NS" rollout status deployment/litellm --timeout=300s >/dev/null
