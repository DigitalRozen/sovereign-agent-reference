#!/usr/bin/env bash
# Check that this machine can run `make up`. Read-only, except that with a running cluster
# it starts and deletes one short-lived probe pod to test NetworkPolicy enforcement.
# Exit code 1 if any check FAILs; WARNs are printed but do not fail.
set -uo pipefail

CLUSTER=sovereign-agent
PORT=8080
MIN_K3D=5.8.0
MIN_MEM_GB=7
GOOD_MEM_GB=12
MIN_DISK_GB=15
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

fails=0
warns=0
pass() { printf '  PASS  %s\n' "$1"; }
warn() { printf '  WARN  %s\n' "$1"; warns=$((warns + 1)); }
fail() { printf '  FAIL  %s\n' "$1"; fails=$((fails + 1)); }

# version_ge A B: true if version A >= version B (dotted numbers).
version_ge() { [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]; }

echo "Platform"
os="$(uname -s)"
if [[ "$os" == "Linux" ]] && grep -qi microsoft /proc/version 2>/dev/null; then
  pass "WSL2 ($(uname -r))"
elif [[ "$os" == "Linux" ]]; then
  pass "Linux ($(uname -r))"
elif [[ "$os" == "Darwin" ]]; then
  warn "macOS: not tested; k3d on Docker Desktop should work, see RUN_LOCAL.md"
else
  fail "unsupported OS: $os (use Linux or WSL2)"
fi

echo "Tools"
for bin in docker k3d kubectl openssl curl uv make column; do
  if command -v "$bin" >/dev/null 2>&1; then
    pass "$bin"
  elif [[ "$bin" == column ]]; then
    fail "column not found on PATH; 'make demo' and 'make audit' need it (Debian/Ubuntu: sudo apt-get install bsdextrautils)"
  else
    fail "$bin not found on PATH"
  fi
done
if command -v k3d >/dev/null 2>&1; then
  k3d_ver="$(k3d version 2>/dev/null | sed -n 's/^k3d version v\{0,1\}\([0-9.]*\).*/\1/p' | head -n1)"
  if [[ -z "$k3d_ver" ]]; then
    warn "could not read the k3d version (need >= $MIN_K3D)"
  elif version_ge "$k3d_ver" "$MIN_K3D"; then
    pass "k3d $k3d_ver >= $MIN_K3D"
  else
    fail "k3d $k3d_ver is too old (need >= $MIN_K3D)"
  fi
fi

echo "Docker"
if ! command -v docker >/dev/null 2>&1; then
  fail "skipped: docker is not installed"
elif ! docker info >/dev/null 2>&1; then
  fail "the Docker daemon is not reachable (is it running? is your user in the docker group?)"
else
  pass "daemon reachable (server $(docker info --format '{{.ServerVersion}}' 2>/dev/null))"
  mem_mib=$(($(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0) / 1024 / 1024))
  mem_gb="$(awk -v m="$mem_mib" 'BEGIN { printf "%.1f", m / 1024 }')"
  if ((mem_mib < MIN_MEM_GB * 1024)); then
    fail "Docker has ${mem_gb} GB memory (need >= ${MIN_MEM_GB} GB; raise it in Docker Desktop or .wslconfig)"
  elif ((mem_mib < GOOD_MEM_GB * 1024)); then
    warn "Docker has ${mem_gb} GB memory (works, but ${GOOD_MEM_GB}+ GB is comfortable)"
  else
    pass "Docker memory ${mem_gb} GB"
  fi
  cpus="$(docker info --format '{{.NCPU}}' 2>/dev/null || echo 0)"
  if ((cpus < 2)); then
    fail "Docker has ${cpus} CPU(s) (need >= 2)"
  elif ((cpus < 4)); then
    warn "Docker has ${cpus} CPUs (first deploy will be slow; 4+ recommended)"
  else
    pass "Docker CPUs ${cpus}"
  fi
  docker_root="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null)"
  # On Docker Desktop the root dir lives inside its VM and is not visible here.
  if [[ -n "$docker_root" && -d "$docker_root" ]]; then
    disk_gb="$(df -Pk "$docker_root" 2>/dev/null | awk 'NR==2 {print int($4 / 1024 / 1024)}')"
    if [[ -z "$disk_gb" ]]; then
      warn "could not read free disk for $docker_root"
    elif ((disk_gb < MIN_DISK_GB)); then
      fail "${disk_gb} GB free for Docker at $docker_root (need >= ${MIN_DISK_GB} GB for images)"
    else
      pass "${disk_gb} GB free for Docker"
    fi
  else
    warn "Docker data dir not visible from this shell; check free disk (>= ${MIN_DISK_GB} GB) yourself"
  fi
fi

echo "Kernel"
if [[ "$os" == "Linux" && -r /proc/sys/fs/inotify/max_user_instances ]]; then
  inst="$(cat /proc/sys/fs/inotify/max_user_instances)"
  if ((inst < 512)); then
    warn "fs.inotify.max_user_instances=$inst; pods may crash with 'too many open files' (fix: sudo sysctl fs.inotify.max_user_instances=512)"
  else
    pass "fs.inotify.max_user_instances=$inst"
  fi
else
  pass "not applicable on $os"
fi
# k3s enforces NetworkPolicy with ipset. Without the kernel's ip_set support it skips
# the policy controller and the sandbox keeps its network. k3s runs on Docker's kernel,
# which with Docker Desktop is not this host's kernel; the probe below is what counts.
docker_os="$(docker info --format '{{.OperatingSystem}}' 2>/dev/null || true)"
docker_kernel="$(docker info --format '{{.KernelVersion}}' 2>/dev/null || true)"
if [[ "$docker_os" == *"Docker Desktop"* ]]; then
  warn "Docker Desktop: k3s runs on Docker's kernel ($docker_kernel), not this host's; the ip_set check below does not cover it. NetworkPolicy enforcement is only known from the cluster probe (see RUN_LOCAL.md)"
fi
if [[ "$os" == "Linux" && "$docker_os" != *"Docker Desktop"* ]]; then
  kver="$(uname -r)"
  if [[ -d /sys/module/ip_set ]]; then
    pass "ip_set kernel module loaded (NetworkPolicy can be enforced)"
  elif grep -qs '/ip_set\.ko' "/lib/modules/$kver/modules.builtin" "/lib/modules/$kver/modules.dep" \
    || zgrep -qsE '^CONFIG_IP_SET=(y|m)' /proc/config.gz 2>/dev/null; then
    pass "ip_set kernel support available (NetworkPolicy can be enforced)"
  else
    warn "no ip_set support found in kernel $kver; k3s will not enforce NetworkPolicy and the sandbox will have network access (see RUN_LOCAL.md)"
  fi
fi

echo "Cluster and port $PORT"
cluster_exists=false
if command -v k3d >/dev/null 2>&1 && k3d cluster list "$CLUSTER" >/dev/null 2>&1; then
  cluster_exists=true
  pass "cluster '$CLUSTER' exists; 'make up' will reuse it"
  if docker logs "k3d-$CLUSTER-server-0" 2>&1 \
    | grep -q 'Skipping network policy controller start, ipset save failed'; then
    warn "k3s skipped its network policy controller (ipset save failed): sandbox isolation is NOT enforced (see RUN_LOCAL.md)"
  fi
  "$ROOT/scripts/netpol-check.sh"
  case $? in
    0) pass "NetworkPolicy enforced: a probe pod in the sandbox namespace cannot reach the Kubernetes API" ;;
    1) warn "NetworkPolicy is NOT enforced: a probe pod in the sandbox namespace reached the Kubernetes API, so model-written code has network access (see RUN_LOCAL.md)" ;;
    *) warn "NetworkPolicy probe was inconclusive (pod did not start or finish); is the cluster healthy?" ;;
  esac
else
  pass "no cluster '$CLUSTER' yet; 'make up' will create it"
fi
port_in_use=false
if command -v ss >/dev/null 2>&1; then
  ss -ltnH "sport = :$PORT" 2>/dev/null | grep -q . && port_in_use=true
elif command -v lsof >/dev/null 2>&1; then
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && port_in_use=true
else
  warn "neither ss nor lsof found; cannot check port $PORT"
fi
if $port_in_use && ! $cluster_exists; then
  fail "port $PORT is already in use; free it or change it in deploy/k3d/cluster.yaml"
elif $port_in_use; then
  pass "port $PORT is in use by the existing cluster"
else
  pass "port $PORT is free"
fi

echo "Configuration"
# Read .env exactly as up.sh does (sourced, with any shell value removed first).
env_key="$(
  unset OPENROUTER_API_KEY
  if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env" >/dev/null 2>&1
  fi
  printf '%s' "${OPENROUTER_API_KEY:-}"
)"
if [[ -n "$env_key" ]]; then
  pass ".env sets OPENROUTER_API_KEY: the agent will use a real model (requests leave the machine)"
else
  pass "no provider key in .env: the agent uses the built-in scripted model, nothing leaves the machine"
fi
if [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
  if [[ -n "$env_key" && "$env_key" != "$OPENROUTER_API_KEY" ]]; then
    warn "OPENROUTER_API_KEY in your shell differs from .env; make up uses the one in .env"
  elif [[ -z "$env_key" ]]; then
    warn "OPENROUTER_API_KEY is set in your shell but not in .env; make up ignores it (only .env counts)"
  fi
fi
if [[ -d "$ROOT/.venv" ]]; then
  pass "Python dev environment present"
else
  warn "no .venv yet; run 'make sync' before 'make smoke' or 'make demo'"
fi

echo
if ((fails > 0)); then
  echo "doctor: $fails failed, $warns warning(s). Fix the FAIL lines before 'make up'."
  exit 1
fi
echo "doctor: ready for 'make up' ($warns warning(s))."
