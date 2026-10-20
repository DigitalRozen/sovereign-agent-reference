"""OIDC authorization code flow with PKCE, plus access-token verification."""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from .config import Settings

APP_ROLES = frozenset({"buyer", "procurement_manager", "viewer"})


@dataclass(frozen=True)
class User:
    username: str
    roles: frozenset[str]
    access_token: str
    expires_at: int


@dataclass(frozen=True)
class LoginRequest:
    url: str
    state: str
    verifier: str


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def login_request(settings: Settings) -> LoginRequest:
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    query = urlencode(
        {
            "client_id": settings.client_id,
            "response_type": "code",
            "scope": "openid",
            "redirect_uri": settings.redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return LoginRequest(
        url=f"{settings.public_auth_url}/protocol/openid-connect/auth?{query}",
        state=state,
        verifier=verifier,
    )


class TokenVerifier:
    def __init__(self, settings: Settings, resolve_key=None) -> None:
        self.issuer = settings.issuer
        if resolve_key is None:
            client = jwt.PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=300)

            def resolve_key(token):
                return client.get_signing_key_from_jwt(token).key

        self._resolve_key = resolve_key

    def user(self, access_token: str) -> User | None:
        try:
            claims = jwt.decode(
                access_token,
                self._resolve_key(access_token),
                algorithms=["RS256"],
                audience="mcp-erp",
                issuer=self.issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError:
            return None
        roles = frozenset(set(claims.get("realm_access", {}).get("roles", [])) & APP_ROLES)
        return User(
            username=claims.get("preferred_username", claims["sub"]),
            roles=roles,
            access_token=access_token,
            expires_at=claims["exp"],
        )


async def exchange_code(settings: Settings, code: str, verifier: str) -> str:
    """Redeem the authorization code over the cluster network. Returns the access token."""
    async with httpx.AsyncClient(timeout=10) as http:
        response = await http.post(
            f"{settings.internal_auth_url}/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.redirect_uri,
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "code_verifier": verifier,
            },
        )
    response.raise_for_status()
    return response.json()["access_token"]
