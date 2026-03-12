"""Transactional email service using Resend.

Handles password-reset and email-verification emails.  When the Resend API key
is not configured the service falls back to logging the email body so that
local development works without credentials.
"""

from __future__ import annotations

import logging
from typing import Any

from homebuyer.config import APP_URL, EMAIL_FROM, RESEND_API_KEY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-load the Resend SDK so the module can be imported even when the
# package is not installed (it's an optional dependency at import time).
# ---------------------------------------------------------------------------

_resend_module: Any = None


def _get_resend() -> Any:
    """Return the ``resend`` module, importing it lazily on first use."""
    global _resend_module  # noqa: PLW0603
    if _resend_module is None:
        try:
            import resend  # type: ignore[import-untyped]

            _resend_module = resend
        except ImportError:
            logger.warning("resend package not installed — email sending disabled")
            return None
    return _resend_module


def is_email_configured() -> bool:
    """Return True if the Resend API key is set and the SDK is available."""
    return bool(RESEND_API_KEY) and _get_resend() is not None


# ---------------------------------------------------------------------------
# Shared HTML wrapper
# ---------------------------------------------------------------------------

_BASE_STYLE = """
    body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f4f5f7; }
    .container { max-width: 560px; margin: 40px auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
    .header { background: #1e293b; padding: 32px 40px; text-align: center; }
    .header h1 { margin: 0; color: #f5a623; font-size: 22px; font-weight: 700; letter-spacing: -0.3px; }
    .header p { margin: 4px 0 0; color: #94a3b8; font-size: 12px; }
    .body { padding: 40px; }
    .body h2 { margin: 0 0 8px; color: #1e293b; font-size: 20px; font-weight: 600; }
    .body p { margin: 0 0 20px; color: #475569; font-size: 15px; line-height: 1.6; }
    .btn { display: inline-block; padding: 14px 32px; background: #f5a623; color: #1e293b !important; font-size: 15px; font-weight: 700; text-decoration: none; border-radius: 8px; }
    .btn:hover { background: #e09600; }
    .code-box { background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; text-align: center; margin: 20px 0; }
    .code-box code { font-size: 22px; font-weight: 700; letter-spacing: 2px; color: #1e293b; font-family: 'SF Mono', 'Fira Code', monospace; }
    .muted { color: #94a3b8; font-size: 13px; }
    .footer { padding: 24px 40px; text-align: center; border-top: 1px solid #e2e8f0; }
    .footer p { margin: 0; color: #94a3b8; font-size: 12px; }
"""


def _wrap_html(inner_html: str) -> str:
    """Wrap inner content in the shared email template."""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{_BASE_STYLE}</style></head>
<body>
<div class="container">
    <div class="header">
        <h1>HomeBuyer</h1>
        <p>Berkeley Price Predictor</p>
    </div>
    <div class="body">
        {inner_html}
    </div>
    <div class="footer">
        <p>HomeBuyer &middot; Berkeley, CA &middot; You received this because you have an account.</p>
    </div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------


def _password_reset_html(reset_url: str, token: str) -> str:
    """Build the HTML body for a password-reset email."""
    inner = f"""\
        <h2>Reset your password</h2>
        <p>
            We received a request to reset the password for your HomeBuyer account.
            Click the button below to choose a new password. This link expires in
            <strong>1 hour</strong>.
        </p>
        <p style="text-align:center;">
            <a href="{reset_url}" class="btn">Reset Password</a>
        </p>
        <p class="muted">
            If the button doesn't work, copy and paste this token into the
            reset form:
        </p>
        <div class="code-box"><code>{token}</code></div>
        <p class="muted">
            If you didn't request this, you can safely ignore this email.
            Your password will not change.
        </p>"""
    return _wrap_html(inner)


def _email_verification_html(verify_url: str, token: str) -> str:
    """Build the HTML body for an email-verification email."""
    inner = f"""\
        <h2>Verify your email</h2>
        <p>
            Thanks for signing up for HomeBuyer! Please confirm your email
            address by clicking the button below. This link expires in
            <strong>24 hours</strong>.
        </p>
        <p style="text-align:center;">
            <a href="{verify_url}" class="btn">Verify Email</a>
        </p>
        <p class="muted">
            If the button doesn't work, copy and paste this token into the
            verification form:
        </p>
        <div class="code-box"><code>{token}</code></div>
        <p class="muted">
            If you didn't create an account, you can safely ignore this email.
        </p>"""
    return _wrap_html(inner)


# ---------------------------------------------------------------------------
# Public send helpers
# ---------------------------------------------------------------------------


def _send(to: str, subject: str, html: str) -> dict | None:
    """Send an email via Resend, or log it in dev mode.

    Returns the Resend response dict on success, or ``None`` if email is
    not configured (dev mode fallback).
    """
    resend = _get_resend()
    if not RESEND_API_KEY or resend is None:
        logger.info(
            "Email not configured — would have sent to %s:\n"
            "  Subject: %s\n"
            "  (set RESEND_API_KEY to enable)",
            to,
            subject,
        )
        return None

    resend.api_key = RESEND_API_KEY
    params: dict = {
        "from": EMAIL_FROM,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    try:
        result = resend.Emails.send(params)
        logger.info("Email sent to %s (id=%s)", to, result.get("id", "?"))
        return result  # type: ignore[return-value]
    except Exception:
        logger.exception("Failed to send email to %s", to)
        return None


def send_password_reset(to: str, token: str) -> dict | None:
    """Send a password-reset email containing *token*.

    The email includes a clickable link (``APP_URL/login?mode=reset&token=...``)
    as well as the raw token for manual entry.
    """
    reset_url = f"{APP_URL}/login?mode=reset&token={token}"
    html = _password_reset_html(reset_url, token)
    return _send(to, "Reset your HomeBuyer password", html)


def send_email_verification(to: str, token: str) -> dict | None:
    """Send an email-verification email containing *token*.

    The email includes a clickable link
    (``APP_URL/login?mode=verify&token=...``) and the raw token.
    """
    verify_url = f"{APP_URL}/login?mode=verify&token={token}"
    html = _email_verification_html(verify_url, token)
    return _send(to, "Verify your HomeBuyer email", html)
