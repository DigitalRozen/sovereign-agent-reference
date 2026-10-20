"""Bearer-token verification against the Keycloak realm.

Every request carries the end user's own access token. It is verified here, on the
tool server, independently of the agent that forwarded it.
"""

from collections.abc import Callable
from dataclasses import dataclass

import anyio
import jwt
from mcp.server.auth.provider import AccessToken

APP_ROLES = frozenset({"buyer", "procurement_manager", "viewer"})

# Resolves the signing key for a raw token. Production uses the realm's JWKS endpoint;
# tests inject a local key.
KeyResolver = Callable[[str], object]


def jwks_key_resolver(jwks_url: str) -> KeyResolver:
    client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=300)
    return lambda token: client.get_signing_key_from_jwt(token).key


@dataclass(frozen=True)
class Caller:
    """The human on whose behalf a tool runs."""

    subject: str
    username: str
    roles: frozenset[str]

    @classmethod
    def from_claims(cls, claims: dict) -> "Caller":
        realm_roles = set(claims.get("realm_access", {}).get("roles", []))
        return cls(
            subject=claims["sub"],
            username=claims.get("preferred_username", claims["sub"]),
            roles=frozenset(realm_roles & APP_ROLES),
        )


class KeycloakTokenVerifier:
    """Implements the MCP SDK's TokenVerifier protocol."""

    def __init__(self, issuer: str, audience: str, resolve_key: KeyResolver) -> None:
        self.issuer = issuer
        self.audience = audience
        self._resolve_key = resolve_key

    def decode(self, token: str) -> dict | None:
        try:
            return jwt.decode(
                token,
                self._resolve_key(token),
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError:
            return None

    async def verify_token(self, token: str) -> AccessToken | None:
        claims = await anyio.to_thread.run_sync(self.decode, token)
        if claims is None:
            return None
        return AccessToken(
            token=token,
            client_id=claims.get("azp", ""),
            scopes=claims.get("scope", "").split(),
            expires_at=claims["exp"],
            resource=self.audience,
            subject=claims["sub"],
            claims=claims,
        )
