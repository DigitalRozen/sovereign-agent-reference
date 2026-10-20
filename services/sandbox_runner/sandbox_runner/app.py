"""HTTP front for the sandbox: verify the caller, create the Job, wait, return its output."""

import hashlib
import json
import os
import time
from dataclasses import dataclass

import jwt
import psycopg
from fastapi import FastAPI, Header, HTTPException
from kubernetes import client, config
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .job import DEADLINE_SECONDS, NAMESPACE, CodeRejected, build_job, job_name

ISSUER = os.environ.get("OIDC_ISSUER", "http://localhost:8080/auth/realms/tarnwick")
JWKS_URL = os.environ.get(
    "OIDC_JWKS_URL",
    "http://keycloak.platform.svc.cluster.local:8080/auth/realms/tarnwick/protocol/openid-connect/certs",
)
AUDIENCE = "sandbox-runner"
ALLOWED_ROLES = frozenset({"buyer", "procurement_manager"})
AUDIT_DSN = os.environ.get("AUDIT_DSN", "")
MAX_OUTPUT_BYTES = 8192
# Pod scheduling and image start come on top of the in-container deadline.
WAIT_SECONDS = DEADLINE_SECONDS + 30

app = FastAPI(title="sandbox-runner")
_jwks = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=300)


class RunRequest(BaseModel):
    code: str = Field(description="Python source. Read input from env SANDBOX_INPUT (JSON).")
    input: dict = Field(default_factory=dict)


@dataclass
class RunResult:
    status: str  # succeeded | failed | timeout
    reason: str
    output: str
    job: str


def caller_from(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        claims = jwt.decode(
            token,
            _jwks.get_signing_key_from_jwt(token).key,
            algorithms=["RS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "invalid token") from exc
    roles = set(claims.get("realm_access", {}).get("roles", []))
    username = claims.get("preferred_username", claims["sub"])
    if not roles & ALLOWED_ROLES:
        audit(username, "sandbox.denied", "denied", {"reason": "role"})
        raise HTTPException(403, f"roles {sorted(ALLOWED_ROLES)} required")
    return username


def audit(actor: str, action: str, decision: str, detail: dict) -> None:
    if not AUDIT_DSN:
        return
    with psycopg.connect(AUDIT_DSN) as conn:
        conn.execute(
            "INSERT INTO audit.events (actor, action, decision, detail) VALUES (%s, %s, %s, %s)",
            (actor, action, decision, Jsonb(detail)),
        )


def _kube() -> tuple[client.BatchV1Api, client.CoreV1Api]:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.BatchV1Api(), client.CoreV1Api()


def _outcome(job: client.V1Job, pod: client.V1Pod | None) -> tuple[str, str] | None:
    status = job.status
    if status.succeeded:
        return "succeeded", "exit 0"
    for condition in status.conditions or []:
        if condition.type == "Failed" and condition.status == "True":
            if condition.reason == "DeadlineExceeded":
                return "timeout", f"killed after {DEADLINE_SECONDS}s"
            terminated = _terminated(pod)
            if terminated is not None:
                return "failed", f"{terminated.reason} (exit {terminated.exit_code})"
            return "failed", condition.reason or "failed"
    return None


def _terminated(pod: client.V1Pod | None):
    if pod is None or not pod.status.container_statuses:
        return None
    return pod.status.container_statuses[0].state.terminated


def run_job(code: str, input_json: str, requested_by: str) -> RunResult:
    batch, core = _kube()
    name = job_name(code)
    batch.create_namespaced_job(NAMESPACE, build_job(name, code, input_json, requested_by))

    deadline = time.monotonic() + WAIT_SECONDS
    outcome, pod = None, None
    while time.monotonic() < deadline:
        pods = core.list_namespaced_pod(NAMESPACE, label_selector=f"job-name={name}").items
        pod = pods[0] if pods else None
        outcome = _outcome(batch.read_namespaced_job(name, NAMESPACE), pod)
        if outcome:
            break
        time.sleep(0.5)
    if outcome is None:
        batch.delete_namespaced_job(name, NAMESPACE, propagation_policy="Background")
        outcome = ("timeout", "did not finish in time")

    output = ""
    if pod is not None:
        try:
            # Raw bytes: the client would otherwise parse JSON-looking logs and return a repr.
            response = core.read_namespaced_pod_log(
                pod.metadata.name,
                NAMESPACE,
                limit_bytes=MAX_OUTPUT_BYTES,
                _preload_content=False,
            )
            output = response.data.decode("utf-8", errors="replace")
        except client.ApiException:
            output = ""
    return RunResult(status=outcome[0], reason=outcome[1], output=output, job=name)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/run")
def run(request: RunRequest, authorization: str | None = Header(default=None)) -> dict:
    username = caller_from(authorization)
    detail = {"code_sha256": hashlib.sha256(request.code.encode()).hexdigest()}
    try:
        result = run_job(request.code, json.dumps(request.input), requested_by=username)
    except CodeRejected as exc:
        audit(username, "sandbox.rejected", "denied", {**detail, "reason": str(exc)})
        raise HTTPException(422, str(exc)) from exc
    audit(
        username,
        "sandbox.run",
        "allowed" if result.status == "succeeded" else "info",
        {**detail, "job": result.job, "status": result.status, "reason": result.reason},
    )
    return result.__dict__
