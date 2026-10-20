"""The LLM gateway authenticates, rate-limits, budgets and attributes every model call."""

import time
import uuid
from collections.abc import Iterator

import httpx
import pytest

from .conftest import port_forward, read_secret

pytestmark = pytest.mark.cluster


@pytest.fixture(scope="module")
def gateway() -> Iterator[str]:
    """The gateway has no Ingress, so tests reach it through a port-forward."""
    with port_forward("litellm", 14000, 4000) as url:
        yield url


@pytest.fixture(scope="module")
def keys() -> dict[str, str]:
    return read_secret("llm-keys")


def chat(gateway: str, key: str | None, model: str = "agent-default") -> httpx.Response:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return httpx.post(
        f"{gateway}/v1/chat/completions",
        headers=headers,
        json={"model": model, "messages": [{"role": "user", "content": "check billet stock"}]},
        timeout=30,
    )


def admin(gateway: str, keys: dict[str, str], path: str, **kwargs) -> httpx.Response:
    headers = {"Authorization": f"Bearer {keys['master-key']}"}
    return httpx.request(kwargs.pop("method", "POST"), f"{gateway}{path}", headers=headers,
                         timeout=30, **kwargs)  # fmt: skip


@pytest.fixture
def temp_key(gateway, keys) -> Iterator[callable]:
    """Create throwaway keys with specific limits, so tests never share counters."""
    created = []

    def make(**limits) -> str:
        body = {"user_id": f"test-{uuid.uuid4().hex[:8]}", "models": ["agent-default"], **limits}
        response = admin(gateway, keys, "/key/generate", json=body)
        assert response.status_code == 200, response.text
        created.append(response.json()["key"])
        return created[-1]

    yield make
    if created:
        admin(gateway, keys, "/key/delete", json={"keys": created})


def test_user_key_can_call_the_model(gateway, keys):
    response = chat(gateway, keys["user-key-alice"])
    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"].startswith("[scripted]")


@pytest.mark.parametrize("key", [None, "sk-not-a-real-key"])
def test_missing_or_unknown_key_is_rejected(gateway, key):
    assert chat(gateway, key).status_code == 401


@pytest.mark.parametrize("user", ["alice", "morgan", "val"])
def test_each_user_key_is_bound_to_that_user_with_limits(gateway, keys, user):
    response = admin(gateway, keys, "/key/info", method="GET",
                     params={"key": keys[f"user-key-{user}"]})  # fmt: skip
    assert response.status_code == 200, response.text
    info = response.json()["info"]
    assert info["user_id"] == user
    assert info["max_budget"] > 0
    assert info["rpm_limit"] > 0


def test_key_cannot_use_a_model_outside_its_allow_list(gateway, temp_key):
    key = temp_key()
    assert chat(gateway, key, model="agent-default").status_code == 200
    assert chat(gateway, key, model="agent-openrouter").status_code in (401, 403)


def test_rate_limit_returns_429(gateway, temp_key):
    key = temp_key(rpm_limit=2)
    statuses = [chat(gateway, key).status_code for _ in range(4)]
    assert statuses[:2] == [200, 200]
    assert 429 in statuses[2:]


def test_budget_blocks_further_calls_once_spent(gateway, temp_key):
    key = temp_key(max_budget=0.000001)
    statuses = []
    for _ in range(10):
        statuses.append(chat(gateway, key).status_code)
        if statuses[-1] != 200:
            break
        time.sleep(1)
    assert statuses[0] == 200
    assert statuses[-1] in (400, 429), statuses


def test_spend_is_attributed_to_the_calling_key(gateway, keys, temp_key):
    key = temp_key()
    assert chat(gateway, key).status_code == 200
    spend = 0.0
    for _ in range(30):  # spend is written to the database in batches
        info = admin(gateway, keys, "/key/info", method="GET", params={"key": key}).json()
        spend = info["info"]["spend"] or 0.0
        if spend > 0:
            break
        time.sleep(1)
    assert spend > 0
