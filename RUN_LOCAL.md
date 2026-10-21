# Running it locally

Everything runs on one machine in a single-node k3s cluster inside Docker (k3d). Nothing is pushed to a registry and, without a provider key, no request leaves the machine.

## 1. Prerequisites

| | Minimum | Comfortable |
|---|---|---|
| OS | Linux or WSL2 (Ubuntu) | same |
| Memory available to Docker | 7 GB | 12 GB+ |
| CPUs available to Docker | 2 | 4+ |
| Free disk for Docker images | 15 GB | 25 GB |

Tools: Docker, [k3d](https://k3d.io) v5.8+, kubectl, openssl, curl, make, `column` and [uv](https://docs.astral.sh/uv/). CI uses k3d v5.8.3. `column` is used by `make demo` and `make audit`; on Debian and Ubuntu it is in the `bsdextrautils` package.

Install on Ubuntu (native or WSL2), after Docker itself:

```bash
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | TAG=v5.8.3 bash
sudo snap install kubectl --classic     # or follow https://kubernetes.io/docs/tasks/tools/
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt-get install -y make openssl curl bsdextrautils
```

**WSL2:** use Docker Desktop with WSL integration enabled, or Docker Engine installed inside the distro. Docker Desktop on WSL2 gets its memory from `%UserProfile%\.wslconfig` (`[wsl2]` → `memory=12GB`); restart WSL (`wsl --shutdown`) after changing it. Clone the repo inside the Linux filesystem (`~/...`), not under `/mnt/c`.

**WSL2 and sandbox isolation:** on WSL2 with Docker Desktop (WSL kernel 6.6, k3d 5.9.0), k3s enforces NetworkPolicy, but about two seconds late: a new pod could reach the network in its first moment (`./scripts/netpol-check.sh --trace` showed `reachable` at t+0.0s, `blocked` from t+2.2s). Before this was handled, `make smoke` failed `test_no_network_not_even_cluster_dns_or_the_kube_api`. The sandbox now starts model code only after the pod sees its own egress blocked (up to 8 seconds), and refuses to run it if that never happens. Native Linux (CI) enforces the policy before the code starts.

**macOS:** not tested. k3d on Docker Desktop should work; give Docker Desktop at least 8 GB (7 GB is the minimum) in *Settings → Resources*.

## 2. Check the machine

```bash
make doctor
```

It is read-only. It checks the tools and the k3d version, that the Docker daemon answers, Docker's memory, CPUs and free disk, the inotify limit, whether port 8080 is free, and whether `.env` will send requests to a real model. Fix every `FAIL` line before continuing; `WARN` lines are worth reading but do not block.

## 3. Run

```bash
cp .env.example .env   # optional: set OPENROUTER_API_KEY to use a real model
make sync              # Python dev dependencies (.venv)
make up                # create cluster, build and import images, deploy, wait
make smoke             # cluster test suite
make creds             # demo logins (generated at deploy time, stored only in the cluster)
make demo              # the scenario from the terminal
```

The first `make up` pulls the k3s, Postgres, Keycloak, LiteLLM and Python base images and builds four service images, so it takes several minutes; later runs reuse the cluster and are much faster. `make up` is safe to re-run: secrets are created only if missing.

Then open **http://localhost:8080/agent/**. Log in as `alice` (buyer) and run the agent, then as `morgan` (manager) to approve the draft, and open the *Audit log*. Keycloak's admin console is at http://localhost:8080/auth/admin. The 3-minute walkthrough is in [docs/demo-script.md](docs/demo-script.md).

## 4. Using a real model

Set `OPENROUTER_API_KEY` in `.env` and run `make up` again. Only `.env` counts: a key exported in your shell is ignored, and `make doctor` warns about it. The key is passed to the cluster on stdin and stored as a Kubernetes Secret; the gateway restarts to pick it up and the agent switches to the `agent-openrouter` model. Agent prompts and ERP data the agent reads are then sent to OpenRouter. To go back to the scripted model, empty the key and run `make up` again; the old key stays in the cluster Secret until `make down`.

## 5. Stop and clean up

```bash
make down                  # deletes the cluster and all its data, including generated secrets
```

Locally built images (`sovereign-agent/*:<git sha>`) stay in Docker; remove them with `docker image rm` if you want the disk back.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `make up` fails creating the cluster: port 8080 is already allocated | Another process listens on 8080. Stop it, or change `8080:80` in `deploy/k3d/cluster.yaml` (the scripts and tests assume 8080, so prefer freeing it). |
| Pods restart with `too many open files` | Raise the inotify limit: `sudo sysctl fs.inotify.max_user_instances=512` (persist it in `/etc/sysctl.d/`). |
| `rollout status deployment/litellm` times out | The LiteLLM image is large and runs database migrations on start. Check `kubectl -n platform logs deployment/litellm`; on a slow connection, re-run `make up`. |
| Keycloak is not reachable on `http://localhost:8080/auth` | Traefik is still starting, or Keycloak ran out of memory. Check `kubectl -n platform get pods` and Docker's memory limit. |
| Image pulls fail or hit rate limits | Check network or proxy access to Docker Hub, quay.io and ghcr.io, then re-run `make up`. |
| A pod stays in `ErrImageNeverPull` | The images are built locally and imported, never pulled, so the import into the node failed. `k3d image import` can log `failed to import images` and still exit 0; `make up` checks every image in the node and retries three times, then stops with `could not import ...`. Run `make up` again; if it keeps failing, `make down && make up`. |
| `make up` or `make doctor` says **NetworkPolicy is NOT enforced**, or `make smoke` fails `test_no_network_not_even_cluster_dns_or_the_kube_api` | k3s's policy controller (built into the k3s process, not a pod) is not filtering traffic, so **sandbox isolation is NOT enforced**. Collect: `docker logs k3d-sovereign-agent-server-0 2>&1 \| grep -iE 'network.?policy\|netpol\|ipset\|iptables-restore' \| tail -20`, `docker exec k3d-sovereign-agent-server-0 iptables-save \| grep -c KUBE-NWPLCY`, `docker exec k3d-sovereign-agent-server-0 ipset list -n \| head` and `docker info --format '{{.OperatingSystem}} {{.KernelVersion}}'`. If the log says `Skipping network policy controller start, ipset save failed`, Docker's kernel lacks `ip_set`: use a kernel with `CONFIG_IP_SET` (with Docker Desktop that is Docker's VM kernel, not your distro's), then `make down && make up`. To tell a late policy from a missing one, run `./scripts/netpol-check.sh --trace`: `reachable` only in the first seconds means it lands late, which the sandbox waits out; `reachable` throughout means it is not enforced. A sandbox run that fails with `sandbox network was not isolated; code not run` is this case. |
| Sandbox tests fail with the sandbox reaching the network, and the output never says `waiting for network isolation` | The cluster runs an old `sandbox-runner`, built before the network guard. Older versions tagged every image `:dev`, so `make up` on an existing cluster left the Deployments "unchanged" and kept the old pods. `make up` now tags images with the git commit (plus a hash of uncommitted changes under `services/`), so changed code always rolls new pods, and it checks that every service pod runs the new tag. `make doctor` reports pods that do not match the checkout. Run `make up` again. |
| On a cluster kept between runs, an agent run ends with *The LLM gateway refused the request* (400 or 429), or `make smoke` fails a viewer or agent test | The demo users' gateway budgets are small on purpose (val: USD 0.05 per 30 days) and spend accumulates across runs. `make smoke` and `make reset-demo` now set the three demo keys' spend back to 0 (`scripts/reset-llm-spend.sh`); budgets and rate limits stay as they are. |
| You want a clean slate | `make down && make up`. New passwords are generated; run `make creds` again. |

For anything else, `kubectl get pods -A` and the logs of the failing pod are the starting point; the CI workflow's *Cluster state on failure* step lists the useful commands.
