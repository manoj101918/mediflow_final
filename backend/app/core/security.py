"""Supabase access-token verification.

Asymmetric tokens (ES256/RS256) are verified against the project's JWKS endpoint; the legacy
HS256 shared secret is accepted only when SUPABASE_JWT_SECRET is configured.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

import jwt
from jwt import PyJWKClient

from app.core.config import Settings, get_settings

_ASYMMETRIC_ALGS = frozenset({"ES256", "RS256"})
_CLOCK_SKEW_SECONDS = 30


class InvalidTokenError(Exception):
    """The bearer token is missing, malformed, expired, or not signed by this project."""


@dataclass(frozen=True)
class TokenClaims:
    user_id: UUID
    email: str | None


class JWTVerifier:
    def __init__(self, settings: Settings) -> None:
        self._audience = settings.jwt_audience
        self._issuer = settings.jwt_issuer
        self._hs256_secret = (
            settings.supabase_jwt_secret.get_secret_value()
            if settings.supabase_jwt_secret
            else None
        )
        self._jwks = PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=600, timeout=5)

    def _signing_key(self, token: str, alg: str) -> Any:
        if alg in _ASYMMETRIC_ALGS:
            try:
                return self._jwks.get_signing_key_from_jwt(token).key
            except jwt.PyJWKClientError as exc:
                raise InvalidTokenError("Unknown signing key") from exc
        if alg == "HS256" and self._hs256_secret:
            return self._hs256_secret
        raise InvalidTokenError("Unsupported token algorithm")

    def verify(self, token: str) -> TokenClaims:
        """Blocking (may fetch JWKS); call from a worker thread in async code."""
        try:
            alg = jwt.get_unverified_header(token).get("alg", "")
            payload = jwt.decode(
                token,
                self._signing_key(token, alg),
                algorithms=[alg],
                audience=self._audience,
                issuer=self._issuer,
                # Tokens are used the instant Supabase issues them, so a server clock slightly
                # ahead of ours yields an `iat` in the future. Tolerate small clock drift.
                leeway=_CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
            return TokenClaims(user_id=UUID(payload["sub"]), email=payload.get("email"))
        except InvalidTokenError:
            raise
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise InvalidTokenError("Invalid token") from exc


@lru_cache
def get_jwt_verifier() -> JWTVerifier:
    return JWTVerifier(get_settings())
