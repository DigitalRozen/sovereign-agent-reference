"""Helpers for tests that run against the live k3d cluster (make smoke)."""

import base64
import contextlib
import json
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import httpx
import pytest

NAMESPACE = "platform"
POD = "postgres-0"
ISSUER = "http://localhost:8080/auth/realms/tarnwick"
TOKEN_URL = f"{ISSUER}/protocol/openid-connect/token"
DEMO_USERS = ("alice", "morgan", "val")


def kubectl(*args: str) -> str:
    return subprocess.run(
        ["kubectl", "-n", NAMESPACE, *args], capture_output=True, text=True, check=True
    ).stdout


def read_secret(name: str) -> dict[str, str]:
    raw = json.loads(kubectl("get", "secret", name, "-o", "json"))["data"]
    return {key: base64.b64decode(value).decode() for key, value in raw.items()}


@contextlib.contextmanager
def port_forward(service: str, local_port: int, remote_port: int) -> Iterator[str]:
    """Reach a cluster-internal Service from the test process."""
    proc = subprocess.Popen(
        [
            "kubectl",
            "-n",
            NAMESPACE,
            "port-forward",
            f"svc/{service}",
            f"{local_port}:{remote_port}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", local_port)) == 0:
                    break
            if time.monotonic() > deadline:
                raise TimeoutError(f"port-forward to {service} did not come up")
            time.sleep(0.2)
        yield f"http://127.0.0.1:{local_port}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def password_grant(client_id: str, username: str, password: str) -> httpx.Response:
    return httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "password",
            "client_id": client_id,
            "username": username,
            "password": password,
            "scope": "openid",
        },
        timeout=10,
    )


@pytest.fixture(scope="session")
def passwords() -> dict[str, str]:
    secret = read_secret("keycloak-credentials")
    return {user: secret[f"demo-password-{user}"] for user in DEMO_USERS}


@pytest.fixture(scope="session")
def user_token(passwords) -> Callable[[str], str]:
    """A fresh access token for a demo user, via the test-only client."""

    def token(username: str) -> str:
        response = password_grant("smoke-test", username, passwords[username])
        response.raise_for_status()
        return response.json()["access_token"]

    return token


@dataclass
class SqlResult:
    ok: bool
    output: str


class Psql:
    """Runs SQL inside the postgres pod as a given role, over TCP so passwords are checked."""

    def __init__(self) -> None:
        secret = read_secret("postgres-credentials")
        self._passwords = {
            "ai_reader": secret["ai-reader-password"],
            "ai_writer": secret["ai-writer-password"],
            "erp_integration": secret["erp-integration-password"],
            "postgres": secret["superuser-password"],
        }

    def run(self, role: str, sql: str) -> SqlResult:
        proc = subprocess.run(
            [
                "kubectl", "-n", NAMESPACE, "exec", "-i", POD, "--",
                "env", f"PGPASSWORD={self._passwords[role]}",
                "psql", "-h", "127.0.0.1", "-U", role, "-d", "erp",
                "-v", "ON_ERROR_STOP=1", "-tA",
            ],
            input=sql, capture_output=True, text=True,
        )  # fmt: skip
        return SqlResult(ok=proc.returncode == 0, output=(proc.stdout + proc.stderr).strip())


@pytest.fixture(scope="session")
def psql() -> Psql:
    return Psql()
