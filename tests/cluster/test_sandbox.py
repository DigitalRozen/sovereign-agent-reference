"""Model-written code runs, but cannot reach the network, the cluster, or the node."""

import json
import subprocess
import textwrap
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from .conftest import port_forward

pytestmark = pytest.mark.cluster


@pytest.fixture(scope="module")
def runner() -> Iterator[str]:
    with port_forward("sandbox-runner", 18100, 8000) as url:
        yield url


def run(runner: str, token: str | None, code: str, input_: dict | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.post(
        f"{runner}/run",
        headers=headers,
        json={"code": textwrap.dedent(code), "input": input_ or {}},
        timeout=90,
    )


def probe(runner: str, token: str, code: str) -> dict:
    """Run code that prints one JSON object; return it."""
    response = run(runner, token, code)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "succeeded", result
    return json.loads(result["output"].strip().splitlines()[-1])


def test_quantity_calculation_runs_and_reads_its_input(runner, user_token):
    code = """
        import json, os
        data = json.loads(os.environ["SANDBOX_INPUT"])
        need = sum(data["demand_kg"]) + data["safety_kg"] - data["available_kg"]
        print(json.dumps({"order_kg": max(0, need)}))
    """
    data = {"demand_kg": [6800, 4300], "safety_kg": 3000, "available_kg": 1800}
    response = run(runner, user_token("alice"), code, data)
    assert response.status_code == 200, response.text
    result = response.json()
    # Show status, reason and guard_log on failure, not just a JSON decode error.
    assert result["status"] == "succeeded", result
    assert json.loads(result["output"]) == {"order_kg": 12300}, result


def test_no_network_not_even_cluster_dns_or_the_kube_api(runner, user_token):
    result = probe(
        runner,
        user_token("alice"),
        r"""
        import json, socket
        def attempt(fn):
            try:
                fn()
                return "reachable"
            except OSError as exc:
                return type(exc).__name__
        def connect(host, port):
            return lambda: socket.create_connection((host, port), timeout=2).close()
        def dns_query():
            # Resolver lookups would retry for longer than the deadline; send one raw query.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                udp.settimeout(2)
                udp.sendto(b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
                           b"\x07example\x03com\x00\x00\x01\x00\x01", ("10.43.0.10", 53))
                udp.recvfrom(512)
        print(json.dumps({
            "cluster_dns_udp": attempt(dns_query),
            "internet": attempt(connect("1.1.1.1", 443)),
            "kube_api": attempt(connect("10.43.0.1", 443)),
        }))
        """,
    )
    assert "reachable" not in result.values(), result


def test_no_credentials_no_root_no_writable_filesystem(runner, user_token):
    result = probe(
        runner,
        user_token("alice"),
        """
        import json, os
        def writable(path):
            try:
                open(path, "w").close()
                return True
            except OSError:
                return False
        print(json.dumps({
            "uid": os.getuid(),
            "sa_token": os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token"),
            # GPG_KEY is the base image's public release-signing key ID, not a secret.
            "env_secrets": [k for k in os.environ
                            if any(w in k for w in ("PASSWORD", "SECRET", "TOKEN", "API_KEY"))
                            or os.environ[k].startswith("sk-")],
            "write_root": writable("/etc/pwned"),
            "write_tmp": writable("/tmp/scratch"),
        }))
        """,
    )
    assert result["uid"] != 0
    assert result["sa_token"] is False
    assert result["env_secrets"] == []
    assert result["write_root"] is False
    assert result["write_tmp"] is True  # a small, size-capped scratch dir is allowed


def test_infinite_loop_is_killed_at_the_deadline(runner, user_token):
    response = run(runner, user_token("alice"), "while True:\n    pass\n")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "timeout"


def test_memory_bomb_is_killed(runner, user_token):
    response = run(runner, user_token("alice"), "x = bytearray(512 * 1024 * 1024)\n")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "failed", result
    assert "OOMKilled" in result["reason"] or "Error" in result["reason"], result


def test_only_buyers_and_managers_may_run_code(runner, user_token):
    assert run(runner, None, "print(1)").status_code == 401
    assert run(runner, "forged", "print(1)").status_code == 401
    assert run(runner, user_token("val"), "print(1)").status_code == 403


def test_runs_are_audited(runner, user_token, psql):
    marker = "audit-probe-7f3a"
    response = run(runner, user_token("morgan"), f"print('{marker}')")
    assert response.json()["status"] == "succeeded"
    audit = psql.run(
        "postgres",
        "SELECT actor || ':' || (detail->>'status') FROM audit.events "
        "WHERE action = 'sandbox.run' ORDER BY event_id DESC LIMIT 1;",
    )
    assert audit.output == "morgan:succeeded"


# --- Late NetworkPolicy -----------------------------------------------------------------
# On WSL2 with Docker Desktop the policy reached a new pod about two seconds after it started.
# CI is fast, so the condition is reproduced here: remove deny-all, start a run, and only
# then put the policy back. The guard in the Job must hold the model's code until then.

POLICY = Path(__file__).parents[2] / "deploy/base/sandbox/network-policy.yaml"
NETWORK_PROBE_CODE = """
    import json, socket
    try:
        socket.create_connection(("10.43.0.1", 443), timeout=2).close()
        print(json.dumps({"kube_api": "reachable"}))
    except OSError as exc:
        print(json.dumps({"kube_api": type(exc).__name__}))
"""


def sandbox_kubectl(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["kubectl", *args], check=True, capture_output=True, text=True
    ).stdout


def wait_for_running_run_pod(timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        running = sandbox_kubectl(
            "-n", "sandbox", "get", "pods", "-l", "role=sandbox-run",
            "--field-selector=status.phase=Running", "-o", "name",
        )  # fmt: skip
        if running.strip():
            return
        time.sleep(0.2)
    raise AssertionError("the sandbox run's pod never started")


@pytest.fixture
def deny_all_removed() -> Iterator[None]:
    """Run with the sandbox's deny-all policy deleted; it is always restored afterwards."""
    sandbox_kubectl("-n", "sandbox", "delete", "networkpolicy", "deny-all")
    time.sleep(3)  # let the policy controller drop the rules
    try:
        yield
    finally:
        sandbox_kubectl("apply", "-f", str(POLICY))
        time.sleep(3)


def test_code_waits_for_a_policy_that_arrives_late(runner, user_token, deny_all_removed):
    result: dict = {}

    def start_run() -> None:
        response = run(runner, user_token("alice"), NETWORK_PROBE_CODE)
        result.update(response.json(), http=response.status_code)

    worker = threading.Thread(target=start_run)
    worker.start()
    wait_for_running_run_pod()
    time.sleep(2)  # the guard is now finding the network open
    sandbox_kubectl("apply", "-f", str(POLICY))
    worker.join(timeout=90)

    assert result.get("http") == 200 and result["status"] == "succeeded", result
    assert "waiting for network isolation" in result["guard_log"], result
    # The guard's message must not leak into the output the agent parses.
    probe_result = json.loads(result["output"])
    assert probe_result["kube_api"] != "reachable", result


def test_code_never_runs_when_the_policy_never_arrives(runner, user_token, deny_all_removed):
    response = run(runner, user_token("alice"), NETWORK_PROBE_CODE)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "failed", result
    assert "not isolated; code not run" in result["reason"], result
    assert "kube_api" not in result["output"], result
    assert "not isolated" in result["guard_log"], result
