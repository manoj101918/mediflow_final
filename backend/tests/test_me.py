import uuid

from fastapi import Depends, FastAPI
from httpx import AsyncClient

from app.db.models import UserRole
from app.deps import require_role
from tests.conftest import ClinicFixture, auth


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


async def test_me_requires_token(client: AsyncClient) -> None:
    response = await client.get("/api/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_me_rejects_invalid_token(client: AsyncClient) -> None:
    response = await client.get("/api/me", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_me_unknown_user(client: AsyncClient) -> None:
    response = await client.get("/api/me", headers=auth(uuid.uuid4()))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NO_PROFILE"


async def test_me_receptionist(client: AsyncClient, clinic: ClinicFixture) -> None:
    user_id = await clinic.add_user(UserRole.RECEPTIONIST)
    response = await client.get("/api/me", headers=auth(user_id))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user_id)
    assert body["role"] == "receptionist"
    assert body["clinic"] == {"id": str(clinic.id), "name": clinic.name, "timezone": "Asia/Kolkata"}
    assert body["doctor_id"] is None


async def test_me_doctor_has_doctor_id(client: AsyncClient, clinic: ClinicFixture) -> None:
    user_id = await clinic.add_user(UserRole.DOCTOR, link_doctor=True)
    response = await client.get("/api/me", headers=auth(user_id))
    assert response.status_code == 200
    assert response.json()["doctor_id"] == str(await clinic.doctor_id_for(user_id))


async def test_me_inactive_account(client: AsyncClient, clinic: ClinicFixture) -> None:
    user_id = await clinic.add_user(UserRole.RECEPTIONIST, active=False)
    response = await client.get("/api/me", headers=auth(user_id))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_INACTIVE"


async def test_require_role_and_validation_envelope(
    app: FastAPI, client: AsyncClient, clinic: ClinicFixture
) -> None:
    @app.get("/api/_test/admin-only", dependencies=[Depends(require_role(UserRole.ADMIN))])
    async def admin_only(n: int) -> dict[str, int]:
        return {"n": n}

    receptionist = await clinic.add_user(UserRole.RECEPTIONIST)
    admin = await clinic.add_user(UserRole.ADMIN)

    forbidden = await client.get("/api/_test/admin-only?n=1", headers=auth(receptionist))
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "FORBIDDEN"

    ok = await client.get("/api/_test/admin-only?n=1", headers=auth(admin))
    assert ok.status_code == 200

    invalid = await client.get("/api/_test/admin-only?n=abc", headers=auth(admin))
    assert invalid.status_code == 422
    error = invalid.json()["error"]
    assert error["code"] == "VALIDATION"
    assert error["details"][0]["loc"] == ["query", "n"]
    assert "abc" not in invalid.text


async def test_unknown_route_uses_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
