"""Authentication utilities: password hashing, JWT tokens, and FastAPI dependencies."""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr

from homebuyer.config import JWT_ACCESS_TOKEN_EXPIRE_MINUTES, JWT_ALGORITHM, JWT_SECRET_KEY

# Refresh token lifetime (7 days)
REFRESH_TOKEN_EXPIRE_DAYS = 7

# ---------------------------------------------------------------------------
# Password hashing (using bcrypt directly — passlib is unmaintained)
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def validate_password(password: str) -> list[str]:
    """Validate password complexity. Returns a list of failure messages (empty = valid)."""
    errors: list[str] = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one digit")
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?`~]", password):
        errors.append("Password must contain at least one special character")
    return errors


# ---------------------------------------------------------------------------
# JWT access tokens
# ---------------------------------------------------------------------------


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Refresh tokens (opaque, stored hashed in DB)
# ---------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    """SHA-256 hash of a raw refresh token for storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_refresh_token(db, user_id: int) -> str:
    """Generate an opaque refresh token, store its hash in the DB, and return the raw token."""
    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_token(raw_token)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    ).strftime("%Y-%m-%d %H:%M:%S")
    db.create_refresh_token(
        user_id=user_id, token_hash=token_hash, expires_at=expires_at
    )
    return raw_token


def validate_refresh_token(db, raw_token: str) -> dict:
    """Validate a raw refresh token. Returns the DB row.

    Raises HTTPException on invalid/expired/revoked tokens.
    """
    token_hash = _hash_token(raw_token)
    row = db.get_refresh_token_by_hash(token_hash)
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if row.get("revoked"):
        raise HTTPException(status_code=401, detail="Refresh token has been revoked")
    # Check expiry
    expires_at = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    )
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=401, detail="Refresh token has expired")
    return row


# ---------------------------------------------------------------------------
# Pydantic models for auth requests/responses
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str] = None


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse
    tos_update_required: bool = False


# ---------------------------------------------------------------------------
# FastAPI dependency for protected endpoints
# ---------------------------------------------------------------------------

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# Cookie name for HttpOnly access token
ACCESS_TOKEN_COOKIE = "homebuyer_access"


def set_access_cookie(response, token: str) -> None:
    """Set the access token as an HttpOnly cookie on the response."""
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=token,
        httponly=True,
        secure=True,         # Only sent over HTTPS (browsers ignore for localhost)
        samesite="lax",      # CSRF protection — sent on same-site + top-level navigations
        max_age=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


def clear_access_cookie(response) -> None:
    """Delete the access token cookie."""
    response.delete_cookie(
        key=ACCESS_TOKEN_COOKIE,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def get_current_user_id(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
) -> int:
    """Extract and validate the user ID from a JWT bearer token.

    Checks in order:
    1. Authorization: Bearer <token> header (for API clients)
    2. HttpOnly cookie (for browser clients)

    Raises HTTPException 401 if no valid token is found.
    """
    # Prefer Authorization header, fall back to cookie
    effective_token = token or request.cookies.get(ACCESS_TOKEN_COOKIE)

    if effective_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(effective_token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id: Optional[int] = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return int(user_id)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_optional_user_id(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[int]:
    """Extract the user ID from a JWT if present, otherwise return None.

    Unlike get_current_user_id, this does NOT raise 401 for unauthenticated
    requests. Used for endpoints that work for both authenticated and
    anonymous users (e.g., Faketor chat).
    """
    effective_token = token or request.cookies.get(ACCESS_TOKEN_COOKIE)
    if effective_token is None:
        return None
    try:
        payload = jwt.decode(effective_token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id: Optional[int] = payload.get("sub")
        return int(user_id) if user_id is not None else None
    except (JWTError, ValueError, TypeError):
        return None
