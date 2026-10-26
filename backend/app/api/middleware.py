import hmac
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.api.deps import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, REFRESH_COOKIE
from app.api.errors import error_body

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
DOCS_CSP = (
    "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; frame-ancestors 'none'"
)

Handler = Callable[[Request], Awaitable[Response]]


async def csrf_protection(request: Request, call_next: Handler) -> Response:
    """Double submit token: state changing requests that carry a session cookie must echo
    the csrf cookie in a custom header. Browsers cannot add that header cross-site without
    a CORS preflight, which the origin allowlist refuses."""
    if request.method in UNSAFE_METHODS and (
        request.cookies.get(ACCESS_COOKIE) or request.cookies.get(REFRESH_COOKIE)
    ):
        cookie = request.cookies.get(CSRF_COOKIE, "")
        header = request.headers.get(CSRF_HEADER, "")
        if not cookie or not header or not hmac.compare_digest(cookie, header):
            return JSONResponse(error_body(403, "CSRF validation failed", request), status_code=403)
    return await call_next(request)


async def security_headers(request: Request, call_next: Handler) -> Response:
    response = await call_next(request)
    docs = request.url.path.startswith(DOCS_PATHS)
    response.headers["Content-Security-Policy"] = DOCS_CSP if docs else API_CSP
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response
