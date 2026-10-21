#!/usr/bin/env bash
# Print the tag for locally built service images: the git commit, plus a content hash of
# uncommitted changes under services/. A fixed tag (the old ":dev") never changes the
# Deployments, so `make up` on an existing cluster kept running the previous code.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! sha="$(git rev-parse --short=12 HEAD 2>/dev/null)"; then
  echo "nogit-$(date -u +%Y%m%d%H%M%S)"
  exit 0
fi
dirty="$(
  {
    git diff HEAD -- services
    git ls-files --others --exclude-standard -z -- services | xargs -0r cat
  } | sha1sum | cut -c1-8
)"
if [[ -z "$(git status --porcelain -- services)" ]]; then
  echo "$sha"
else
  echo "$sha-dirty-$dirty"
fi
