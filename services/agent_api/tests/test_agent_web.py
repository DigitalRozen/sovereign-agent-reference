import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
from agent_api import web
from agent_api.config import settings
from agent_api.oidc import login_request, pkce_pair
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    return TestClient(web.app, follow_redirects=False)


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert challenge == expected.decode()
    assert len(verifier) >= 43


def test_login_redirect_uses_code_flow_with_pkce_and_state():
    login = login_request(settings)
    url = urlparse(login.url)
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.path.endswith("/realms/tarnwick/protocol/openid-connect/auth")
    assert params["response_type"] == "code"
    assert params["code_challenge_method"] == "S256"
    assert params["state"] == login.state
    assert params["client_id"] == "agent-ui"
    assert "client_secret" not in params


def test_login_route_remembers_state_for_the_callback(client):
    response = client.get("/agent/login")
    assert response.status_code == 303
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    assert state in web.pending_logins


def test_callback_with_unknown_state_is_rejected(client):
    assert client.get("/agent/callback?code=abc&state=forged").status_code == 400


@pytest.mark.parametrize("path", ["/agent/drafts", "/agent/audit", "/agent/runs/x"])
def test_pages_require_a_session(client, path):
    response = client.get(path)
    assert response.status_code == 303
    assert response.headers["location"] == "/agent/login"


def test_actions_require_a_session(client):
    assert client.post("/agent/ask", data={"question": "hi"}).status_code == 303
    assert client.post("/agent/drafts/1/approve").status_code == 303


def test_api_requires_a_valid_bearer_token(client):
    assert client.post("/agent/api/ask", json={"question": "hi"}).status_code == 401
    headers = {"Authorization": "Bearer junk"}
    assert (
        client.post("/agent/api/ask", json={"question": "hi"}, headers=headers).status_code == 401
    )
