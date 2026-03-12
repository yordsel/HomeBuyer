"""Comprehensive tests for authentication endpoints.

Covers registration, login, logout, token refresh, password management,
email verification, account lifecycle, TOS, and activity logging.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from fastapi.testclient import TestClient

from homebuyer.storage.database import Database


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STRONG_PASSWORD = "Test1234!@"
STRONG_PASSWORD_ALT = "NewPass5678#"
TEST_EMAIL = "test@example.com"
TEST_NAME = "Test User"
TOS_VERSION = "1.0"


def _register(client: TestClient, email=TEST_EMAIL, password=STRONG_PASSWORD, tos=TOS_VERSION):
    """Helper: register a user and return the response."""
    return client.post("/api/auth/register", json={
        "email": email,
        "password": password,
        "full_name": TEST_NAME,
        "accepted_tos_version": tos,
    })


def _login(client: TestClient, email=TEST_EMAIL, password=STRONG_PASSWORD):
    """Helper: login and return the response."""
    return client.post("/api/auth/login", json={
        "email": email,
        "password": password,
    })


def _auth_header(access_token: str) -> dict:
    """Helper: construct Authorization header."""
    return {"Authorization": f"Bearer {access_token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def auth_db(tmp_path):
    """Create a fresh database with schema for auth tests.

    Uses check_same_thread=False because FastAPI TestClient runs
    requests in a separate thread from the test thread.
    """
    db_path = tmp_path / "auth_test.db"
    db = Database(db_path)
    db.connect(check_same_thread=False)
    db.initialize_schema()
    yield db
    db.close()


@pytest.fixture()
def client(auth_db):
    """FastAPI TestClient with a patched _state pointing at the test DB.

    The TestClient triggers the app lifespan which creates a real AppState.
    We patch _state *after* the client starts so the DB points at our test DB.
    Rate limiting is disabled to avoid flaky tests.
    """
    import homebuyer.api as api_module

    # Disable rate limiting for tests
    original_enabled = api_module.limiter.enabled
    api_module.limiter.enabled = False

    with TestClient(api_module.app, raise_server_exceptions=False) as tc:
        # Swap the DB to our test DB after lifespan has initialized _state
        real_db = api_module._state.db
        api_module._state.db = auth_db
        yield tc
        # Restore original DB so lifespan shutdown works cleanly
        api_module._state.db = real_db

    api_module.limiter.enabled = original_enabled


@pytest.fixture()
def registered_user(client):
    """Register a default user and return (client, auth_response_json)."""
    resp = _register(client)
    assert resp.status_code == 200, resp.text
    return client, resp.json()


# ---------------------------------------------------------------------------
# Registration Tests
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_success(self, client):
        resp = _register(client)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == TEST_EMAIL
        assert data["user"]["full_name"] == TEST_NAME
        assert data["token_type"] == "bearer"

    def test_register_sets_httponly_cookie(self, client):
        resp = _register(client)
        assert resp.status_code == 200
        cookies = resp.headers.get_list("set-cookie")
        cookie_str = " ".join(cookies)
        assert "homebuyer_access" in cookie_str
        assert "httponly" in cookie_str.lower()

    def test_register_missing_tos(self, client):
        resp = client.post("/api/auth/register", json={
            "email": TEST_EMAIL,
            "password": STRONG_PASSWORD,
            "full_name": TEST_NAME,
        })
        assert resp.status_code == 400
        assert "Terms" in resp.json()["detail"]

    def test_register_weak_password_short(self, client):
        resp = _register(client, password="Ab1!")
        assert resp.status_code == 400
        assert "8 characters" in resp.json()["detail"]

    def test_register_weak_password_no_uppercase(self, client):
        resp = _register(client, password="test1234!@")
        assert resp.status_code == 400
        assert "uppercase" in resp.json()["detail"]

    def test_register_weak_password_no_lowercase(self, client):
        resp = _register(client, password="TEST1234!@")
        assert resp.status_code == 400
        assert "lowercase" in resp.json()["detail"]

    def test_register_weak_password_no_digit(self, client):
        resp = _register(client, password="TestTest!@")
        assert resp.status_code == 400
        assert "digit" in resp.json()["detail"]

    def test_register_weak_password_no_special(self, client):
        resp = _register(client, password="TestTest12")
        assert resp.status_code == 400
        assert "special" in resp.json()["detail"]

    def test_register_duplicate_email(self, client):
        resp1 = _register(client)
        assert resp1.status_code == 200
        resp2 = _register(client)
        assert resp2.status_code == 409
        assert "already exists" in resp2.json()["detail"]

    def test_register_invalid_email(self, client):
        resp = _register(client, email="not-an-email")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Login Tests
# ---------------------------------------------------------------------------


class TestLogin:
    def test_login_success(self, registered_user):
        client, _ = registered_user
        resp = _login(client)
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == TEST_EMAIL

    def test_login_wrong_password(self, registered_user):
        client, _ = registered_user
        resp = _login(client, password="WrongPass1!")
        assert resp.status_code == 401
        assert "Invalid email or password" in resp.json()["detail"]

    def test_login_nonexistent_email(self, client):
        resp = _login(client, email="nobody@example.com")
        assert resp.status_code == 401
        assert "Invalid email or password" in resp.json()["detail"]

    def test_login_deactivated_account(self, registered_user):
        client, auth_data = registered_user
        # Deactivate
        client.post("/api/auth/deactivate",
                     json={"password": STRONG_PASSWORD},
                     headers=_auth_header(auth_data["access_token"]))
        # Try logging in
        resp = _login(client)
        assert resp.status_code == 403
        assert "deactivated" in resp.json()["detail"]

    def test_login_sets_httponly_cookie(self, registered_user):
        client, _ = registered_user
        resp = _login(client)
        cookies = resp.headers.get_list("set-cookie")
        cookie_str = " ".join(cookies)
        assert "homebuyer_access" in cookie_str
        assert "httponly" in cookie_str.lower()

    def test_login_tos_update_required(self, registered_user):
        """When TOS version changes, login should flag tos_update_required."""
        client, _ = registered_user
        with patch("homebuyer.api.CURRENT_TOS_VERSION", "2.0"):
            resp = _login(client)
        assert resp.status_code == 200
        assert resp.json()["tos_update_required"] is True


# ---------------------------------------------------------------------------
# Token Refresh Tests
# ---------------------------------------------------------------------------


class TestTokenRefresh:
    def test_refresh_success(self, registered_user):
        client, auth_data = registered_user
        resp = client.post("/api/auth/refresh", json={
            "refresh_token": auth_data["refresh_token"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        # New refresh token should be different (opaque random token)
        assert data["refresh_token"] != auth_data["refresh_token"]

    def test_refresh_rotates_token(self, registered_user):
        """After refresh, the old refresh token should be revoked."""
        client, auth_data = registered_user
        old_refresh = auth_data["refresh_token"]
        # Use it once
        resp1 = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert resp1.status_code == 200
        # Try using the old token again — should fail
        resp2 = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert resp2.status_code == 401

    def test_refresh_invalid_token(self, client):
        resp = client.post("/api/auth/refresh", json={
            "refresh_token": "totally-invalid-token",
        })
        assert resp.status_code == 401

    def test_refresh_deactivated_user(self, registered_user):
        """Refresh should fail if user has been deactivated."""
        client, auth_data = registered_user
        # Login again to get a fresh refresh token (the first one is from register)
        login_resp = _login(client)
        new_refresh = login_resp.json()["refresh_token"]
        new_access = login_resp.json()["access_token"]

        # Deactivate
        client.post("/api/auth/deactivate",
                     json={"password": STRONG_PASSWORD},
                     headers=_auth_header(new_access))

        # Try to refresh — should fail because all tokens are revoked on deactivation
        resp = client.post("/api/auth/refresh", json={"refresh_token": new_refresh})
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Logout Tests
# ---------------------------------------------------------------------------


class TestLogout:
    def test_logout_revokes_refresh(self, registered_user):
        client, auth_data = registered_user
        resp = client.post("/api/auth/logout", json={
            "refresh_token": auth_data["refresh_token"],
        })
        assert resp.status_code == 200
        # Refresh token should now be invalid
        resp2 = client.post("/api/auth/refresh", json={
            "refresh_token": auth_data["refresh_token"],
        })
        assert resp2.status_code == 401

    def test_logout_clears_cookie(self, registered_user):
        client, auth_data = registered_user
        resp = client.post("/api/auth/logout", json={
            "refresh_token": auth_data["refresh_token"],
        })
        cookies = resp.headers.get_list("set-cookie")
        cookie_str = " ".join(cookies)
        # Cookie should be cleared (max-age=0 or expires in past)
        assert "homebuyer_access" in cookie_str


# ---------------------------------------------------------------------------
# Password Change Tests
# ---------------------------------------------------------------------------


class TestChangePassword:
    def test_change_password_success(self, registered_user):
        client, auth_data = registered_user
        resp = client.post("/api/auth/change-password",
                           json={"current_password": STRONG_PASSWORD, "new_password": STRONG_PASSWORD_ALT},
                           headers=_auth_header(auth_data["access_token"]))
        assert resp.status_code == 200
        # Old password should no longer work
        resp2 = _login(client, password=STRONG_PASSWORD)
        assert resp2.status_code == 401
        # New password should work
        resp3 = _login(client, password=STRONG_PASSWORD_ALT)
        assert resp3.status_code == 200

    def test_change_password_wrong_current(self, registered_user):
        client, auth_data = registered_user
        resp = client.post("/api/auth/change-password",
                           json={"current_password": "WrongCurr1!", "new_password": STRONG_PASSWORD_ALT},
                           headers=_auth_header(auth_data["access_token"]))
        assert resp.status_code == 400
        assert "incorrect" in resp.json()["detail"].lower()

    def test_change_password_weak_new(self, registered_user):
        client, auth_data = registered_user
        resp = client.post("/api/auth/change-password",
                           json={"current_password": STRONG_PASSWORD, "new_password": "weak"},
                           headers=_auth_header(auth_data["access_token"]))
        assert resp.status_code == 400

    def test_change_password_revokes_all_tokens(self, registered_user):
        client, auth_data = registered_user
        # Change password
        client.post("/api/auth/change-password",
                    json={"current_password": STRONG_PASSWORD, "new_password": STRONG_PASSWORD_ALT},
                    headers=_auth_header(auth_data["access_token"]))
        # Old refresh token should be revoked
        resp = client.post("/api/auth/refresh", json={
            "refresh_token": auth_data["refresh_token"],
        })
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Password Reset Tests
# ---------------------------------------------------------------------------


class TestPasswordReset:
    def test_forgot_password_existing_email(self, registered_user):
        client, _ = registered_user
        resp = client.post("/api/auth/forgot-password", json={"email": TEST_EMAIL})
        assert resp.status_code == 200
        assert "reset link" in resp.json()["detail"].lower()

    def test_forgot_password_nonexistent_email(self, client):
        """Should return success to prevent email enumeration."""
        resp = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
        assert resp.status_code == 200

    def test_reset_password_success(self, registered_user, auth_db):
        client, _ = registered_user
        # Create a reset token directly in the DB
        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        user = auth_db.get_user_by_email(TEST_EMAIL)
        auth_db.create_password_reset_token(user_id=user["id"], token_hash=token_hash, expires_at=expires_at)

        resp = client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": STRONG_PASSWORD_ALT,
        })
        assert resp.status_code == 200
        # New password should work
        resp2 = _login(client, password=STRONG_PASSWORD_ALT)
        assert resp2.status_code == 200

    def test_reset_password_invalid_token(self, client):
        resp = client.post("/api/auth/reset-password", json={
            "token": "invalid-token",
            "new_password": STRONG_PASSWORD_ALT,
        })
        assert resp.status_code == 400

    def test_reset_password_expired_token(self, registered_user, auth_db):
        client, _ = registered_user
        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        # Expired 1 hour ago
        expires_at = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        user = auth_db.get_user_by_email(TEST_EMAIL)
        auth_db.create_password_reset_token(user_id=user["id"], token_hash=token_hash, expires_at=expires_at)

        resp = client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": STRONG_PASSWORD_ALT,
        })
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    def test_reset_password_used_token(self, registered_user, auth_db):
        client, _ = registered_user
        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        user = auth_db.get_user_by_email(TEST_EMAIL)
        auth_db.create_password_reset_token(user_id=user["id"], token_hash=token_hash, expires_at=expires_at)

        # Use it once
        resp1 = client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": STRONG_PASSWORD_ALT,
        })
        assert resp1.status_code == 200

        # Try again — should fail
        resp2 = client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": "AnotherPass9!",
        })
        assert resp2.status_code == 400


# ---------------------------------------------------------------------------
# Email Verification Tests
# ---------------------------------------------------------------------------


class TestEmailVerification:
    def test_verify_email_success(self, registered_user, auth_db):
        client, auth_data = registered_user
        # Create a verification token
        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        auth_db.create_email_verification_token(
            user_id=auth_data["user"]["id"], token_hash=token_hash, expires_at=expires_at,
        )

        resp = client.get(f"/api/auth/verify-email?token={raw_token}")
        assert resp.status_code == 200
        assert "verified" in resp.json()["detail"].lower()

    def test_verify_email_invalid_token(self, client):
        resp = client.get("/api/auth/verify-email?token=bad-token")
        assert resp.status_code == 400

    def test_verify_email_expired(self, registered_user, auth_db):
        client, auth_data = registered_user
        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        auth_db.create_email_verification_token(
            user_id=auth_data["user"]["id"], token_hash=token_hash, expires_at=expires_at,
        )

        resp = client.get(f"/api/auth/verify-email?token={raw_token}")
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Account Management Tests
# ---------------------------------------------------------------------------


class TestAccountManagement:
    def test_deactivate_account(self, registered_user):
        client, auth_data = registered_user
        resp = client.post("/api/auth/deactivate",
                           json={"password": STRONG_PASSWORD},
                           headers=_auth_header(auth_data["access_token"]))
        assert resp.status_code == 200
        assert "deactivated" in resp.json()["detail"].lower()

    def test_deactivate_wrong_password(self, registered_user):
        client, auth_data = registered_user
        resp = client.post("/api/auth/deactivate",
                           json={"password": "WrongPass1!"},
                           headers=_auth_header(auth_data["access_token"]))
        assert resp.status_code == 400

    def test_delete_account(self, registered_user):
        client, auth_data = registered_user
        resp = client.request("DELETE", "/api/auth/account",
                              json={"password": STRONG_PASSWORD},
                              headers=_auth_header(auth_data["access_token"]))
        assert resp.status_code == 200
        assert "deleted" in resp.json()["detail"].lower()
        # User should no longer be able to login
        resp2 = _login(client)
        assert resp2.status_code == 401

    def test_delete_wrong_password(self, registered_user):
        client, auth_data = registered_user
        resp = client.request("DELETE", "/api/auth/account",
                              json={"password": "WrongPass1!"},
                              headers=_auth_header(auth_data["access_token"]))
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# TOS Tests
# ---------------------------------------------------------------------------


class TestTOS:
    def test_get_current_tos_version(self, client):
        resp = client.get("/api/terms/current")
        assert resp.status_code == 200
        assert resp.json()["version"] == TOS_VERSION

    def test_accept_tos(self, registered_user):
        client, auth_data = registered_user
        resp = client.post("/api/auth/accept-tos",
                           headers=_auth_header(auth_data["access_token"]))
        assert resp.status_code == 200
        assert resp.json()["version"] == TOS_VERSION


# ---------------------------------------------------------------------------
# Activity Log Tests
# ---------------------------------------------------------------------------


class TestActivityLog:
    def test_activity_log_records_login(self, registered_user):
        client, auth_data = registered_user
        # Login creates an activity event
        _login(client)
        resp = client.get("/api/auth/activity",
                          headers=_auth_header(auth_data["access_token"]))
        assert resp.status_code == 200
        events = resp.json()
        # Should have at least register + login events
        event_types = [e["event_type"] for e in events]
        assert "register" in event_types
        assert "login_success" in event_types

    def test_activity_log_pagination(self, registered_user):
        client, auth_data = registered_user
        resp = client.get("/api/auth/activity?limit=1&offset=0",
                          headers=_auth_header(auth_data["access_token"]))
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) <= 1


# ---------------------------------------------------------------------------
# Protected Endpoint Tests
# ---------------------------------------------------------------------------


class TestProtectedEndpoints:
    def test_me_without_token(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_valid_token(self, registered_user):
        client, auth_data = registered_user
        resp = client.get("/api/auth/me",
                          headers=_auth_header(auth_data["access_token"]))
        assert resp.status_code == 200
        assert resp.json()["email"] == TEST_EMAIL

    def test_me_with_expired_token(self, registered_user):
        """An expired JWT should return 401."""
        client, _ = registered_user
        from homebuyer.auth import create_access_token
        expired_token = create_access_token(
            data={"sub": "1"},
            expires_delta=timedelta(seconds=-1),
        )
        resp = client.get("/api/auth/me",
                          headers=_auth_header(expired_token))
        assert resp.status_code == 401

    def test_me_with_cookie(self, registered_user):
        """Authentication should work via HttpOnly cookie when no header is sent."""
        client, auth_data = registered_user
        # Set the cookie manually on the client
        client.cookies.set("homebuyer_access", auth_data["access_token"])
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.json()["email"] == TEST_EMAIL


# ---------------------------------------------------------------------------
# Security Headers Tests
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    def test_security_headers_present(self, client):
        resp = client.get("/api/health")
        assert "x-frame-options" in resp.headers
        assert resp.headers["x-frame-options"] == "DENY"
        assert "x-content-type-options" in resp.headers
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert "referrer-policy" in resp.headers
        assert "permissions-policy" in resp.headers
        assert "content-security-policy" in resp.headers

    def test_csp_allows_map_tiles(self, client):
        resp = client.get("/api/health")
        csp = resp.headers["content-security-policy"]
        assert "tile.openstreetmap.org" in csp
        assert "nominatim.openstreetmap.org" in csp
