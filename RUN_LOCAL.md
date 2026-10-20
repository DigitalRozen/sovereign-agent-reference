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

Set `OPENROUTER_API_KEY` in `.env` and run `make up` again. The key is passed to the cluster on stdin and stored as a Kubernetes Secret; the gateway restarts to pick it up and the agent switches to the `agent-openrouter` model. Agent prompts and ERP data the agent reads are then sent to OpenRouter. To go back to the scripted model, empty the key and run `make up` again; the old key stays in the cluster Secret until `make down`.

## 5. Stop and clean up

```bash
make down                  # deletes the cluster and all its data, including generated secrets
```

Locally built images (`sovereign-agent/*:dev`) stay in Docker; remove them with `docker image rm` if you want the disk back.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `make up` fails creating the cluster: port 8080 is already allocated | Another process listens on 8080. Stop it, or change `8080:80` in `deploy/k3d/cluster.yaml` (the scripts and tests assume 8080, so prefer freeing it). |
| Pods restart with `too many open files` | Raise the inotify limit: `sudo sysctl fs.inotify.max_user_instances=512` (persist it in `/etc/sysctl.d/`). |
| `rollout status deployment/litellm` times out | The LiteLLM image is large and runs database migrations on start. Check `kubectl -n platform logs deployment/litellm`; on a slow connection, re-run `make up`. |
| Keycloak is not reachable on `http://localhost:8080/auth` | Traefik is still starting, or Keycloak ran out of memory. Check `kubectl -n platform get pods` and Docker's memory limit. |
| Image pulls fail or hit rate limits | Check network or proxy access to Docker Hub, quay.io and ghcr.io, then re-run `make up`. |
| A pod stays in `ErrImageNeverPull` | The images are built locally and imported, never pulled, so the import into the node failed. `k3d image import` can log `failed to import images` and still exit 0; `make up` checks every image in the node and retries three times, then stops with `could not import ...`. Run `make up` again; if it keeps failing, `make down && make up`. |
| The k3s log says `Skipping network policy controller start, ipset save failed` (see it with `docker logs k3d-sovereign-agent-server-0`) | The host kernel has no `ip_set` support, so k3s does not enforce NetworkPolicy. **Sandbox isolation is then NOT enforced**: model-written code can reach the network, and `make smoke` fails `test_no_network_not_even_cluster_dns_or_the_kube_api`. `make doctor` warns about this. Use a kernel with `CONFIG_IP_SET` (load it with `sudo modprobe ip_set` if it is a module), then `make down && make up`. |
| You want a clean slate | `make down && make up`. New passwords are generated; run `make creds` again. |

For anything else, `kubectl get pods -A` and the logs of the failing pod are the starting point; the CI workflow's *Cluster state on failure* step lists the useful commands.
