"""Visitor customers (DD31, log D4): one new customer per demo conversation, from a template."""

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import DBAPIError

from dale.erp_sim.public import SessionCustomer, VisitorCodeConflictError
from dale.shared.errors import ErrorCode, Failure, Ok, Result
from dale.shared.ids import CompanyId, CustomerId, IdGenerator

logger = logging.getLogger(__name__)
CODE_PREFIX = "V-"
ATTEMPTS = 2  # the first code and one retry on a unique conflict


def random_code() -> str:
    """`V-` plus 10 random hex digits (40 bits), from the system's secure source."""
    return CODE_PREFIX + secrets.token_hex(5).upper()


@dataclass(frozen=True, slots=True)
class VisitorTemplate:
    """The active customer a visitor copies: its company, zone and name."""

    company_id: CompanyId
    company_name: str
    zone_id: UUID
    name: str


class VisitorData(Protocol):
    def visitor_template(self, company_slug: str, code: str) -> VisitorTemplate | None:
        """The active customer with that code, within the company with that slug."""
        ...

    def insert_visitor(self, template: VisitorTemplate, customer_id: CustomerId, code: str) -> bool:
        """Inserts an active customer like the template; False when the code is already taken."""
        ...


def create_visitor(
    company_slug: str,
    template_code: str,
    data: VisitorData,
    ids: IdGenerator,
    codes: Callable[[], str] = random_code,
) -> Result[SessionCustomer]:
    try:
        template = data.visitor_template(company_slug, template_code)
        if template is None:
            return Failure(ErrorCode.CUSTOMER_NOT_FOUND)
        for _ in range(ATTEMPTS):
            customer_id = CustomerId(ids.new_id())
            if data.insert_visitor(template, customer_id, codes()):
                return Ok(SessionCustomer(template.company_id, template.company_name, customer_id))
    except DBAPIError as error:  # fail closed: no conversation, and no shared customer (W14)
        logger.error("create_visitor failed: %s", type(error).__name__)
        return Failure(ErrorCode.RULES_UNAVAILABLE)
    raise VisitorCodeConflictError(f"{ATTEMPTS} visitor codes in a row were taken")
