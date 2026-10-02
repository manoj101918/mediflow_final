"""JWT verification with real signatures (no network: the JWKS lookup is stubbed)."""

import time
import uuid
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config import Settings
from app.core.security import InvalidTokenError, JWTVerifier

SUPABASE_URL = "https://example-ref.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
HS_SECRET = "legacy-test-secret-that-is-long-enough-for-hs256"


def _settings(*, hs_secret: str | None = None) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        supabase_url=SUPABASE_URL,
        supabase_service_role_key="service",
        supabase_jwt_secret=hs_secret,
        inbound_api_key="inbound",
    )


def _claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": str(uuid.uuid4()),
        "email": "reception1@mediflow.test",
        "aud": "authenticated",
        "iss": ISSUER,
        "iat": now,
        "exp": now + 600,
        "role": "authenticated",
    }
    claims.update(overrides)
    return claims


@pytest.fixture
def ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def verifier(ec_key: ec.EllipticCurvePrivateKey, monkeypatch: pytest.MonkeyPatch) -> JWTVerifier:
    v = JWTVerifier(_settings())
    monkeypatch.setattr(
        v._jwks,
        "get_signing_key_from_jwt",
        lambda _token: SimpleNamespace(key=ec_key.public_key()),
    )
    return v


def _es256(key: ec.EllipticCurvePrivateKey, claims: dict[str, Any]) -> str:
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": "test"})


def test_valid_es256_token(verifier: JWTVerifier, ec_key: ec.EllipticCurvePrivateKey) -> None:
    claims = _claims()
    result = verifier.verify(_es256(ec_key, claims))
    assert str(result.user_id) == claims["sub"]
    assert result.email == claims["email"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 120},
        {"aud": "anon"},
        {"iss": "https://evil.example.com/auth/v1"},
        {"sub": "not-a-uuid"},
    ],
    ids=["expired", "wrong-audience", "wrong-issuer", "bad-sub"],
)
def test_rejects_bad_claims(
    verifier: JWTVerifier, ec_key: ec.EllipticCurvePrivateKey, overrides: dict[str, Any]
) -> None:
    with pytest.raises(InvalidTokenError):
        verifier.verify(_es256(ec_key, _claims(**overrides)))


def test_tolerates_small_clock_skew(
    verifier: JWTVerifier, ec_key: ec.EllipticCurvePrivateKey
) -> None:
    # Supabase's clock may be slightly ahead: iat a few seconds in the future must pass.
    now = int(time.time())
    verifier.verify(_es256(ec_key, _claims(iat=now + 5)))


def test_rejects_far_future_iat(verifier: JWTVerifier, ec_key: ec.EllipticCurvePrivateKey) -> None:
    now = int(time.time())
    with pytest.raises(InvalidTokenError):
        verifier.verify(_es256(ec_key, _claims(iat=now + 300, exp=now + 900)))


def test_rejects_missing_exp(verifier: JWTVerifier, ec_key: ec.EllipticCurvePrivateKey) -> None:
    claims = _claims()
    del claims["exp"]
    with pytest.raises(InvalidTokenError):
        verifier.verify(_es256(ec_key, claims))


def test_rejects_token_signed_by_other_key(verifier: JWTVerifier) -> None:
    other = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(InvalidTokenError):
        verifier.verify(_es256(other, _claims()))


def test_rejects_unsigned_token(verifier: JWTVerifier) -> None:
    token = jwt.encode(_claims(), key="", algorithm="none")
    with pytest.raises(InvalidTokenError):
        verifier.verify(token)


def test_rejects_garbage(verifier: JWTVerifier) -> None:
    with pytest.raises(InvalidTokenError):
        verifier.verify("not.a.jwt")


def test_hs256_rejected_without_secret(verifier: JWTVerifier) -> None:
    token = jwt.encode(_claims(), HS_SECRET, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        verifier.verify(token)


def test_hs256_accepted_with_secret() -> None:
    v = JWTVerifier(_settings(hs_secret=HS_SECRET))
    claims = _claims()
    assert str(v.verify(jwt.encode(claims, HS_SECRET, algorithm="HS256")).user_id) == claims["sub"]


def test_hs256_wrong_secret() -> None:
    v = JWTVerifier(_settings(hs_secret=HS_SECRET))
    token = jwt.encode(_claims(), "another-secret-that-is-also-long-enough-x", algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        v.verify(token)
