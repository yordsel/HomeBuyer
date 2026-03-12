"""Security headers middleware for FastAPI.

Adds standard security headers to every HTTP response:
- Content-Security-Policy
- X-Frame-Options
- X-Content-Type-Options
- Strict-Transport-Security (HTTPS only)
- Referrer-Policy
- Permissions-Policy
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# Production CSP — tuned for SPA + Leaflet map tiles + OpenStreetMap geocoding
_CSP_PRODUCTION = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",  # Tailwind + Leaflet inline styles
    "img-src 'self' data: https://*.tile.openstreetmap.org https://unpkg.com",
    "connect-src 'self' https://nominatim.openstreetmap.org",
    "font-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])

# Development CSP — relaxed for Vite HMR (hot module replacement)
_CSP_DEVELOPMENT = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-eval'",  # Vite HMR needs eval
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https://*.tile.openstreetmap.org https://unpkg.com",
    "connect-src 'self' http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:* https://nominatim.openstreetmap.org",
    "font-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security headers on every response."""

    def __init__(self, app, environment: str = "development"):
        super().__init__(app)
        self.environment = environment
        self.csp = _CSP_PRODUCTION if environment == "production" else _CSP_DEVELOPMENT

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        response.headers["Content-Security-Policy"] = self.csp
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )

        # HSTS only when served over HTTPS (detected via reverse proxy header)
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if forwarded_proto == "https" or self.environment == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )

        return response
