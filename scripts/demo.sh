#!/usr/bin/env bash
# Run the procurement scenario from the terminal and print what happened at each layer.
# The same scenario can be clicked through in the browser at http://localhost:8080/agent/
set -euo pipefail

BASE=http://localhost:8080
TOKEN_URL="$BASE/auth/realms/tarnwick/protocol/openid-connect/token"

secret() {
  kubectl -n platform get secret keycloak-credentials -o "jsonpath={.data.$1}" | base64 -d
}

# Test-only client with the password grant; the browser flow uses code + PKCE.
token_for() {
  curl -fsS "$TOKEN_URL" -d grant_type=password -d client_id=smoke-test \
    -d username="$1" --data-urlencode password="$(secret "demo-password-$1")" |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
}

echo "== 1. alice (buyer) asks the agent"
QUESTION="We are short on 6063 billet. Check stock and prepare a purchase order if needed."
curl -fsS "$BASE/agent/api/ask" -H "Authorization: Bearer $(token_for alice)" \
  -H "Content-Type: application/json" -d "{\"question\": \"$QUESTION\"}" |
  python3 "$(dirname "$0")/print_run.py"

echo
echo "== 2. Open the UI to approve as morgan (manager): $BASE/agent/drafts"
echo "   Logins: make creds"
echo
echo "== 3. Latest audit events"
kubectl -n platform exec postgres-0 -- psql -U postgres -d erp -tA -c \
  "SELECT to_char(occurred_at, 'HH24:MI:SS'), actor, action, decision
     FROM audit.events ORDER BY event_id DESC LIMIT 12" | column -t -s '|'
