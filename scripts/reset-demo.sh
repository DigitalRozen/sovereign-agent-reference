#!/usr/bin/env bash
# Put the running demo back to its seed state for a clean recording take: no drafts, no ERP
# orders, no agent runs or app sessions, nobody logged in to Keycloak, and an empty audit log.
# The old audit table is not emptied (it cannot be): it is renamed and stays append-only.
set -euo pipefail

BASE=http://localhost:8080
ARCHIVE="events_until_$(date -u +%Y%m%d_%H%M%S)"

psql_erp() {
  kubectl -n platform exec -i postgres-0 -- psql -U postgres -d erp -v ON_ERROR_STOP=1 "$@"
}

echo "== Drafts and ERP orders back to the seed state; audit log archived as audit.$ARCHIVE"
# Renaming the table is DDL, which the append-only triggers do not cover: this is the
# database superuser limitation described in docs/adr/0009-append-only-audit-in-postgres.md.
psql_erp -q <<SQL
BEGIN;
TRUNCATE ai.po_drafts, erp.purchase_orders RESTART IDENTITY;

ALTER TABLE audit.events RENAME TO $ARCHIVE;
REVOKE INSERT ON audit.$ARCHIVE FROM ai_writer, erp_integration;
CREATE TABLE audit.events (LIKE audit.$ARCHIVE INCLUDING ALL);
CREATE TRIGGER events_append_only
    BEFORE UPDATE OR DELETE ON audit.events
    FOR EACH ROW EXECUTE FUNCTION audit.reject_change();
CREATE TRIGGER events_no_truncate
    BEFORE TRUNCATE ON audit.events
    FOR EACH STATEMENT EXECUTE FUNCTION audit.reject_change();
GRANT INSERT ON audit.events TO ai_writer, erp_integration;
GRANT SELECT ON audit.events TO audit_reader;
COMMIT;
SQL

echo "== Agent runs and app sessions (in memory): restarting agent-api"
# A rolling restart lets the ingress keep the old pod's address for a while and spread
# requests over old and new (504s). Instead: scale to zero, wait until the ingress itself
# reports no backend (404 or 503), then scale up and wait for steady answers.
status() { curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$BASE/agent/healthz" || true; }
kubectl -n platform scale deployment/agent-api --replicas=0 >/dev/null
# No pods left to wait for is fine: it errors with "no matching resources".
kubectl -n platform wait --for=delete pod -l app=agent-api --timeout=90s >/dev/null 2>&1 || true
for _ in $(seq 60); do
  code="$(status)"
  [[ "$code" == 404 || "$code" == 503 ]] && break
  sleep 1
done
kubectl -n platform scale deployment/agent-api --replicas=1 >/dev/null
kubectl -n platform rollout status deployment/agent-api --timeout=120s >/dev/null
ok=0
for _ in $(seq 90); do
  if [[ "$(status)" == 200 ]]; then ok=$((ok + 1)); else ok=0; fi
  ((ok >= 5)) && break
  sleep 1
done
((ok >= 5)) || { echo "agent-api is not answering steadily on $BASE/agent/" >&2; exit 1; }

echo "== Keycloak: ending every session in realm tarnwick"
admin_password="$(kubectl -n platform get secret keycloak-credentials \
  -o jsonpath='{.data.admin-password}' | base64 -d)"
# The password goes on stdin so it never appears in a process listing.
admin_token="$(printf '%s' "$admin_password" |
  curl -fsS "$BASE/auth/realms/master/protocol/openid-connect/token" \
    -d grant_type=password -d client_id=admin-cli -d username=admin \
    --data-urlencode password@- |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
curl -fsS -o /dev/null -X POST -H "Authorization: Bearer $admin_token" \
  "$BASE/auth/admin/realms/tarnwick/logout-all"

counts="$(psql_erp -tA -c "SELECT (SELECT count(*) FROM ai.po_drafts) || ' drafts, '
  || (SELECT count(*) FROM erp.purchase_orders) || ' ERP orders, '
  || (SELECT count(*) FROM audit.events) || ' audit events'")"
echo
echo "Demo reset: $counts. Logins are unchanged ('make creds')."
