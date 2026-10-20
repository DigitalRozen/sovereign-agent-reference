import time

import anyio
import pytest
from mcp_erp.auth import Caller


def verify(verifier, token):
    return anyio.run(verifier.verify_token, token)


def test_valid_token_yields_caller_with_app_roles_only(verifier, make_token):
    access = verify(verifier, make_token("morgan", roles=("procurement_manager",)))
    assert access is not None
    assert access.subject == "sub-morgan"
    caller = Caller.from_claims(access.claims)
    assert caller.username == "morgan"
    assert caller.roles == {"procurement_manager"}  # default-roles-tarnwick is dropped


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "account"},  # issued for another audience
        {"iss": "http://evil.example.com/realms/tarnwick"},
        {"exp": int(time.time()) - 10},
    ],
    ids=["wrong-audience", "wrong-issuer", "expired"],
)
def test_token_is_rejected(verifier, make_token, overrides):
    assert verify(verifier, make_token(**overrides)) is None


def test_token_signed_by_another_key_is_rejected(verifier):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        {"iss": verifier.issuer, "aud": "mcp-erp", "sub": "x", "iat": 0, "exp": 2**31},
        other,
        algorithm="RS256",
    )
    assert verify(verifier, forged) is None


def test_unsigned_token_is_rejected(verifier):
    import jwt

    unsigned = jwt.encode(
        {"iss": verifier.issuer, "aud": "mcp-erp", "sub": "x", "iat": 0, "exp": 2**31},
        key=None,
        algorithm="none",
    )
    assert verify(verifier, unsigned) is None
