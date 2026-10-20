.PHONY: help doctor sync lint fmt test up down smoke creds demo audit reset-demo

CLUSTER := sovereign-agent

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

doctor: ## Check this machine can run the cluster (read-only)
	./scripts/doctor.sh

sync: ## Install dev dependencies
	uv sync

lint: ## Lint and check formatting
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Auto-format
	uv run ruff check --fix .
	uv run ruff format .

test: ## Run unit tests (no cluster needed)
	uv run pytest -q -m "not cluster"

up: ## Create the local k3d cluster and deploy everything
	./scripts/up.sh

down: ## Delete the local cluster and all its data
	k3d cluster delete $(CLUSTER)

smoke: ## Run tests against the running cluster
	uv run pytest -q -m cluster

creds: ## Print demo user logins
	./scripts/creds.sh

demo: ## Run the procurement scenario from the terminal
	./scripts/demo.sh

audit: ## Show the latest audit events and that the table rejects deletes
	./scripts/audit.sh

reset-demo: ## Clear drafts, orders, runs and sessions; start a new audit table (for a clean take)
	./scripts/reset-demo.sh
