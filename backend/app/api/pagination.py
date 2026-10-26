"""One way to page a list: `limit` and `offset` query parameters, and the total in `X-Total-Count`."""

from dataclasses import dataclass
from typing import Any, TypeVar

from fastapi import Query, Response
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")
MAX_LIMIT = 200


@dataclass(frozen=True)
class Page:
    limit: int
    offset: int


def page_params(
    limit: int = Query(50, ge=1, le=MAX_LIMIT, description="Items per page"),
    offset: int = Query(0, ge=0, description="Items to skip"),
) -> Page:
    return Page(limit, offset)


def page_params_large(
    limit: int = Query(200, ge=1, le=MAX_LIMIT, description="Items per page"),
    offset: int = Query(0, ge=0, description="Items to skip"),
) -> Page:
    """For lists that were never paged: everything up to 200 unless the caller asks for less."""
    return Page(limit, offset)


def paged(db: Session, stmt: Select[Any], page: Page, response: Response) -> list[Any]:
    """Run `stmt` for one page and put the total number of matching rows in the response header."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    response.headers["X-Total-Count"] = str(total)
    return list(db.scalars(stmt.limit(page.limit).offset(page.offset)))
