"""One error format. Every error response keeps FastAPI's `detail` and adds an `error` object:

    {"detail": ..., "error": {"code": "not_found", "message": "...", "status": 404, "request_id": "..."}}

`code` is stable for a client to branch on; `message` is for people; `request_id` matches the
`X-Request-ID` response header and the server log line.
"""

import logging
import re
import uuid
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("processledger.api")
REQUEST_ID_HEADER = "X-Request-ID"
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "bad_gateway",
    503: "unavailable",
}


def request_id_of(request: Request) -> str:
    return str(getattr(request.state, "request_id", "") or "")


def error_body(
    status: int, detail: Any, request: Request, message: str | None = None
) -> dict[str, Any]:
    if message is None:
        message = (
            detail
            if isinstance(detail, str)
            else (
                detail.get("message")
                if isinstance(detail, dict) and "message" in detail
                else "The request could not be completed"
            )
        )
    return {
        "detail": detail,
        "error": {
            "code": CODES.get(status, "error"),
            "message": str(message),
            "status": status,
            "request_id": request_id_of(request),
        },
    }


async def request_id_middleware(request: Request, call_next: Any) -> Any:
    supplied = request.headers.get(REQUEST_ID_HEADER, "")
    request.state.request_id = supplied if _VALID_ID.match(supplied) else uuid.uuid4().hex
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request.state.request_id
    return response


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        error_body(exc.status_code, exc.detail, request),
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 without the submitted values: a rejected value must not be echoed back."""
    errors = [
        {"type": e.get("type"), "loc": list(e.get("loc", ())), "msg": e.get("msg")}
        for e in exc.errors()
    ]
    first = errors[0] if errors else {"loc": [], "msg": "Invalid request"}
    where = ".".join(str(p) for p in first["loc"] if p != "body")
    message = f"{where}: {first['msg']}" if where else str(first["msg"])
    return JSONResponse(
        jsonable_encoder(error_body(422, errors, request, message)), status_code=422
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log the failure with the request id; tell the caller nothing about it but the id."""
    log.error(
        "unhandled error on %s %s (request %s): %s",
        request.method,
        request.url.path,
        request_id_of(request),
        type(exc).__name__,
    )
    return JSONResponse(
        error_body(500, "Internal server error", request),
        status_code=500,
        headers={REQUEST_ID_HEADER: request_id_of(request)},
    )


async def rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    """429 in the common format, with a Retry-After hint (the limits are per minute)."""
    return JSONResponse(
        error_body(429, "Too many requests, try again shortly", request),
        status_code=429,
        headers={"Retry-After": "60"},
    )
