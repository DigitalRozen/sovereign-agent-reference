"""Settings, all from the environment. Secrets arrive from Kubernetes Secrets at runtime."""

import os
from dataclasses import dataclass, field

REALM_PATH = "/realms/tarnwick"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # The browser talks to Keycloak's public URL; this pod talks to it over the cluster network.
    public_auth_url: str = _env("KEYCLOAK_PUBLIC_URL", "http://localhost:8080/auth") + REALM_PATH
    internal_auth_url: str = (
        _env("KEYCLOAK_INTERNAL_URL", "http://keycloak.platform.svc.cluster.local:8080/auth")
        + REALM_PATH
    )
    client_id: str = "agent-ui"
    client_secret: str = _env("AGENT_UI_CLIENT_SECRET")
    redirect_uri: str = _env("AGENT_REDIRECT_URI", "http://localhost:8080/agent/callback")

    gateway_url: str = _env("LLM_GATEWAY_URL", "http://litellm.platform.svc.cluster.local:4000")
    model: str = _env("AGENT_MODEL", "agent-default") or "agent-default"
    # One gateway key per user, so budgets and spend are per person, not per agent.
    llm_keys: dict[str, str] = field(
        default_factory=lambda: {
            user: key
            for user in ("alice", "morgan", "val")
            if (key := _env(f"LLM_KEY_{user.upper()}"))
        }
    )

    mcp_url: str = _env("MCP_ERP_URL", "http://mcp-erp.platform.svc.cluster.local:8000")
    sandbox_url: str = _env("SANDBOX_URL", "http://sandbox-runner.platform.svc.cluster.local:8000")

    reader_dsn: str = _env("AI_READER_DSN")
    writer_dsn: str = _env("AI_WRITER_DSN")
    audit_dsn: str = _env("AUDIT_READER_DSN")

    max_steps: int = 8

    @property
    def issuer(self) -> str:
        return self.public_auth_url

    @property
    def jwks_url(self) -> str:
        return f"{self.internal_auth_url}/protocol/openid-connect/certs"


settings = Settings()
