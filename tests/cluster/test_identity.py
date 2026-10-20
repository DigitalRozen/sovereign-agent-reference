"""Keycloak issues tokens that downstream services can verify and authorize on."""

import jwt
import pytest

from .conftest import ISSUER, password_grant

pytestmark = pytest.mark.cluster

JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"

EXPECTED_ROLES = {
    "alice": "buyer",
    "morgan": "procurement_manager",
    "val": "viewer",
}
APP_ROLES = set(EXPECTED_ROLES.values())


def verified_claims(access_token: str) -> dict:
    signing_key = jwt.PyJWKClient(JWKS_URL).get_signing_key_from_jwt(access_token)
    return jwt.decode(
        access_token,
        signing_key.key,
        algorithms=["RS256"],
        audience="mcp-erp",
        issuer=ISSUER,
    )


@pytest.mark.parametrize("username", sorted(EXPECTED_ROLES))
def test_each_user_gets_a_verifiable_token_with_exactly_their_role(passwords, username):
    response = password_grant("smoke-test", username, passwords[username])
    assert response.status_code == 200, response.text

    claims = verified_claims(response.json()["access_token"])
    assert claims["preferred_username"] == username
    app_roles = set(claims["realm_access"]["roles"]) & APP_ROLES
    assert app_roles == {EXPECTED_ROLES[username]}


def test_buyer_cannot_approve(passwords):
    """Separation of duties: the person who requests a PO is not the one who approves it."""
    response = password_grant("smoke-test", "alice", passwords["alice"])
    claims = verified_claims(response.json()["access_token"])
    assert "procurement_manager" not in claims["realm_access"]["roles"]


def test_wrong_password_is_rejected(passwords):
    response = password_grant("smoke-test", "morgan", passwords["morgan"] + "x")
    # RFC 6749 section 5.2: bad resource-owner credentials are a 400 invalid_grant.
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
    assert "access_token" not in response.json()


def test_agent_ui_client_does_not_allow_password_grant(passwords):
    """The real application client only supports the browser flow (code + PKCE)."""
    response = password_grant("agent-ui", "alice", passwords["alice"])
    assert response.status_code in (400, 401)
    assert response.json()["error"] in ("unauthorized_client", "invalid_client")


def test_tampered_token_fails_verification(passwords):
    token = password_grant("smoke-test", "val", passwords["val"]).json()["access_token"]
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[:-4]}AAAA"
    with pytest.raises(jwt.InvalidSignatureError):
        verified_claims(tampered)
