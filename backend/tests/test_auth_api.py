"""Tests for the authentication endpoints (app.api.auth)."""


def test_health_is_ok(client):
    assert client.get("/health").status_code == 200


def test_register_returns_user_without_password_fields(client):
    response = client.post(
        "/auth/register",
        json={"email": "a@example.com", "full_name": "Ada", "password": "supersecret123"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "a@example.com"
    assert "password" not in body
    assert "hashed_password" not in body


def test_duplicate_email_is_conflict(client):
    payload = {"email": "a@example.com", "password": "supersecret123"}
    client.post("/auth/register", json=payload)
    assert client.post("/auth/register", json=payload).status_code == 409


def test_login_with_wrong_password_is_unauthorized(client):
    client.post("/auth/register", json={"email": "a@example.com", "password": "supersecret123"})
    response = client.post("/auth/login", json={"email": "a@example.com", "password": "not-it"})
    assert response.status_code == 401


def test_me_requires_authentication(client):
    assert client.get("/auth/me").status_code in (401, 403)


def test_me_returns_the_authenticated_user(client, auth_headers):
    response = client.get("/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "tester@example.com"
