"""What demo mode shares with the page (DD42, DD43): the notice and the visitor.

`NOTICE.version` names the banner and privacy wording the visitor accepts; a wording change bumps
it and regenerates `contracts/v1/notice.json` (the schema generator writes it from this
constant). `NOTICE.retention_days` is the retention that wording states: the host refuses to
start when its setting differs (slice 9e).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Notice:
    version: int
    retention_days: int


NOTICE = Notice(version=1, retention_days=30)


@dataclass(frozen=True, slots=True)
class Visitor:
    """Who a demo request is from: the keyed hash of the session cookie, which owns the
    conversation, and the client address, which only the limits read. Neither is stored or
    logged in clear, so both stay out of `repr`. Ownership compares `session_hash` alone, never
    `==` on the visitor: a mobile visitor's address changes while the session stays."""

    session_hash: bytes = field(repr=False)
    client_ip: str = field(repr=False)
