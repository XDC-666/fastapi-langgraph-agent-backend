"""Authentication boundary regressions."""
from app.utils.security import create_access_token


def test_non_integer_jwt_subject_returns_401(client):
    token = create_access_token("not-an-integer")
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "无效或过期的凭证"
