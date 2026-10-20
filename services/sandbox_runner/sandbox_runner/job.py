"""The Job spec for one sandboxed run. Pure data, so every isolation setting is unit-tested.

Isolation layers, outermost first:
- namespace `sandbox` enforces Pod Security "restricted" and a deny-all NetworkPolicy
- no service account token, no service links, no host namespaces
- non-root, read-only root filesystem, all capabilities dropped, RuntimeDefault seccomp
- CPU, memory and a small /tmp are capped; the Job is killed after a hard deadline
What this does NOT give: kernel-level isolation. A container escape would reach the node.
"""

import hashlib
import secrets

NAMESPACE = "sandbox"
IMAGE = "python:3.13.13-slim"
MAX_CODE_BYTES = 16_000
DEADLINE_SECONDS = 15
UID = 65534  # nobody


class CodeRejected(ValueError):
    pass


def job_name(code: str) -> str:
    return f"run-{hashlib.sha256(code.encode()).hexdigest()[:8]}-{secrets.token_hex(3)}"


def build_job(name: str, code: str, input_json: str, requested_by: str) -> dict:
    if len(code.encode()) > MAX_CODE_BYTES:
        raise CodeRejected(f"code is larger than {MAX_CODE_BYTES} bytes")
    if not code.strip():
        raise CodeRejected("code is empty")

    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": NAMESPACE,
            "labels": {"app.kubernetes.io/part-of": "sovereign-agent", "role": "sandbox-run"},
            "annotations": {"sovereign-agent/requested-by": requested_by},
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": DEADLINE_SECONDS,
            "ttlSecondsAfterFinished": 300,
            "template": {
                "metadata": {"labels": {"role": "sandbox-run"}},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "enableServiceLinks": False,
                    "hostNetwork": False,
                    "hostPID": False,
                    "hostIPC": False,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": UID,
                        "runAsGroup": UID,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "run",
                            "image": IMAGE,
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["python", "-I", "-c", code],
                            "env": [{"name": "SANDBOX_INPUT", "value": input_json}],
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "64Mi"},
                                "limits": {"cpu": "500m", "memory": "128Mi"},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],  # noqa: S108 - pod-local emptyDir
                        }
                    ],
                    "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": "16Mi"}}],
                },
            },
        },
    }
