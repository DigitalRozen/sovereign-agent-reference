import socket
import subprocess
import sys

import pytest
from sandbox_runner.job import (
    DEADLINE_SECONDS,
    MAX_CODE_BYTES,
    NAMESPACE,
    NOT_ISOLATED_EXIT,
    CodeRejected,
    build_job,
    guard_script,
    job_name,
)


@pytest.fixture
def job():
    return build_job("run-test", "print(1)", "{}", requested_by="alice")


def pod(job):
    return job["spec"]["template"]["spec"]


def container(job):
    return pod(job)["containers"][0]


def test_job_lands_in_the_isolated_namespace_and_never_retries(job):
    assert job["metadata"]["namespace"] == NAMESPACE
    assert job["spec"]["backoffLimit"] == 0
    assert job["spec"]["activeDeadlineSeconds"] == DEADLINE_SECONDS
    assert pod(job)["restartPolicy"] == "Never"


def test_pod_gets_no_credentials_and_no_service_discovery(job):
    spec = pod(job)
    assert spec["automountServiceAccountToken"] is False
    assert spec["enableServiceLinks"] is False
    assert not (spec["hostNetwork"] or spec["hostPID"] or spec["hostIPC"])
    assert not any("TOKEN" in e["name"] or "KEY" in e["name"] for e in container(job)["env"])


def test_container_is_locked_down_to_pod_security_restricted(job):
    assert pod(job)["securityContext"]["runAsNonRoot"] is True
    assert pod(job)["securityContext"]["runAsUser"] != 0
    assert pod(job)["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    sc = container(job)["securityContext"]
    assert sc["allowPrivilegeEscalation"] is False
    assert sc["readOnlyRootFilesystem"] is True
    assert sc["capabilities"] == {"drop": ["ALL"]}


def test_resources_are_capped(job):
    limits = container(job)["resources"]["limits"]
    assert limits == {"cpu": "500m", "memory": "128Mi"}
    assert pod(job)["volumes"][0]["emptyDir"]["sizeLimit"] == "16Mi"


def test_python_runs_isolated_from_environment_and_cwd(job):
    assert container(job)["command"][:3] == ["python", "-I", "-c"]


def test_model_code_runs_only_behind_the_network_guard(job):
    command = container(job)["command"]
    assert command[3] == guard_script()
    assert command[4] == "print(1)"


def run_guarded(probe, code, wait=1.0):
    return subprocess.run(  # noqa: S603 - fixed interpreter and test-owned arguments
        [sys.executable, "-I", "-c", guard_script(probe, wait), code],
        capture_output=True,
        text=True,
        timeout=10,
    )


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_guard_runs_the_code_once_the_network_is_blocked():
    result = run_guarded(("127.0.0.1", free_port()), "import sys; print('ran', sys.argv)")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ran ['-c']"


def test_guard_refuses_to_run_code_while_the_network_is_reachable():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        result = run_guarded(listener.getsockname(), "print('ran')")
    assert result.returncode == NOT_ISOLATED_EXIT
    assert "ran" not in result.stdout
    assert "not isolated" in result.stderr


def test_oversized_or_empty_code_is_rejected():
    with pytest.raises(CodeRejected):
        build_job("x", "x" * (MAX_CODE_BYTES + 1), "{}", "alice")
    with pytest.raises(CodeRejected):
        build_job("x", "   ", "{}", "alice")


def test_job_names_are_unique_and_valid_dns_labels():
    names = {job_name("print(1)") for _ in range(20)}
    assert len(names) == 20
    assert all(len(n) <= 63 and n.replace("-", "").isalnum() for n in names)
