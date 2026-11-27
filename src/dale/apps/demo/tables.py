"""Tables of the `demo` schema (design §5, DD33). Migration 0006 creates them and grants them
table by table; this is the query model, and `alembic check` compares the two.

Nothing here belongs to a company or references `erp` or `brain`, so the reseed never reaches
it (O11): the control row, the spend ledger, the counters and the transcripts survive a reset.
Money is integer micro-USD.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import BYTEA, JSONB

from dale.shared.db_naming import NAMING_CONVENTION

METADATA = sa.MetaData(schema="demo", naming_convention=NAMING_CONVENTION)
REASONS = ("initial", "operator", "reset", "deploy")
RESET_RESULTS = ("ok", "drain_timeout", "reseed_failed")
EVENT_KINDS = ("customer_text", "event", "usage", "error")
HOST_COUNTS = ("live", "in_flight", "transcript_failures", "reset_failures")
TOKENS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _at(name: str, nullable: bool = False) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _not_negative(*columns: str) -> list[sa.CheckConstraint]:
    return [sa.CheckConstraint(f"{c} >= 0", name=c) for c in columns]


def _one_of(column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} IN ({', '.join(repr(v) for v in values)})", name=column)


def _single_row() -> list[sa.schema.SchemaItem]:
    return [
        sa.Column("id", sa.SmallInteger, primary_key=True),
        sa.CheckConstraint("id = 1", name="id"),
    ]


control = sa.Table(
    "control",
    METADATA,
    *_single_row(),
    sa.Column("paused", sa.Boolean, nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    _at("changed_at"),
    _at("reset_requested_at", nullable=True),
    _at("last_reset_at", nullable=True),
    sa.Column("last_reset_result", sa.Text),
    _one_of("reason", REASONS),
    _one_of("last_reset_result", RESET_RESULTS),
)

host_status = sa.Table(
    "host_status",
    METADATA,
    *_single_row(),
    *(sa.Column(c, sa.Integer, nullable=False) for c in HOST_COUNTS),
    _at("started_at"),
    _at("updated_at"),
    *_not_negative(*HOST_COUNTS),
)

spend_day = sa.Table(
    "spend_day",
    METADATA,
    sa.Column("day", sa.Date, primary_key=True),
    sa.Column("committed_micros", sa.BigInteger, nullable=False),
    *_not_negative("committed_micros"),
)

spend_request = sa.Table(
    "spend_request",
    METADATA,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("day", sa.Date, nullable=False),
    sa.Column("model", sa.Text, nullable=False),
    sa.Column("reserved_micros", sa.BigInteger, nullable=False),
    sa.Column("cost_micros", sa.BigInteger),  # null until settled
    *(sa.Column(c, sa.Integer) for c in TOKENS),  # null when unknown
    sa.Column("outcome", sa.Text, nullable=False),
    _at("created_at"),
    _at("settled_at", nullable=True),
    sa.CheckConstraint("reserved_micros > 0", name="reserved_micros"),
    *_not_negative("cost_micros", *TOKENS),
    sa.CheckConstraint("(cost_micros IS NULL) = (settled_at IS NULL)", name="settled"),
)

counter = sa.Table(
    "counter",
    METADATA,
    sa.Column("day", sa.Date, primary_key=True),
    sa.Column("kind", sa.Text, primary_key=True),
    sa.Column("subject", BYTEA, primary_key=True),  # a keyed hash, never a clear IP (O3)
    sa.Column("count", sa.Integer, nullable=False),
    sa.CheckConstraint("count > 0", name="count"),
)

transcript = sa.Table(
    "transcript",
    METADATA,
    sa.Column("conversation_ref", sa.Uuid, primary_key=True),
    sa.Column("session_hash", BYTEA, nullable=False),  # keyed, never the raw token (O2)
    sa.Column("notice_version", sa.Integer, nullable=False),
    sa.Column("brain_conversation_id", sa.Uuid, nullable=False),
    _at("started_at"),
    sa.CheckConstraint("notice_version > 0", name="notice_version"),
)

transcript_event = sa.Table(
    "transcript_event",
    METADATA,
    sa.Column("conversation_ref", sa.Uuid, primary_key=True),
    sa.Column("seq", sa.Integer, primary_key=True),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("body", JSONB, nullable=False),
    _at("at"),
    sa.ForeignKeyConstraint(
        ["conversation_ref"], ["demo.transcript.conversation_ref"], ondelete="CASCADE"
    ),
    _one_of("kind", EVENT_KINDS),
    *_not_negative("seq"),
)
