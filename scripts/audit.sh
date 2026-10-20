#!/usr/bin/env bash
# Print the latest audit events, then show that the table rejects a delete, even by the superuser.
set -euo pipefail

psql_erp() {
  kubectl -n platform exec postgres-0 -- psql -U postgres -d erp "$@"
}

echo "== Latest audit events"
psql_erp -tA -c \
  "SELECT event_id, to_char(occurred_at, 'HH24:MI:SS'), actor, action, decision
     FROM audit.events ORDER BY event_id DESC LIMIT 12" | column -t -s '|'

echo
echo "== DELETE FROM audit.events, as the database superuser"
out="$(psql_erp -v ON_ERROR_STOP=1 -c "DELETE FROM audit.events" 2>&1 || true)"
if [[ "$out" != *"append-only"* ]]; then
  echo "unexpected: the delete was not rejected" >&2
  echo "$out" >&2
  exit 1
fi
echo "   $(grep -m1 ERROR <<<"$out")"
echo "   rows left: $(psql_erp -tA -c "SELECT count(*) FROM audit.events")"
