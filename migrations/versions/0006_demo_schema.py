"""The demo schema: kill switch, host status, spend ledger, counters, transcripts (design §5).

Additive only (DD46): the previous image never reads `demo`, so it keeps working. Grants are
explicit, table by table, and only to dale_app. No default privileges are set in this schema,
so a later table gets nothing until its own migration grants it. dale_verifier gets nothing at
all, not even USAGE (R11), and PUBLIC loses what a new schema could give it. The control row
starts paused for the reason `initial` (DD33): a fresh database fails closed.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"

DDL = """
CREATE SCHEMA demo AUTHORIZATION dale_owner;
REVOKE ALL ON SCHEMA demo FROM PUBLIC;
GRANT USAGE ON SCHEMA demo TO dale_app;

CREATE TABLE demo.control (
  id smallint NOT NULL, paused boolean NOT NULL, reason text NOT NULL,
  changed_at timestamptz NOT NULL, reset_requested_at timestamptz,
  last_reset_at timestamptz, last_reset_result text,
  CONSTRAINT pk_control PRIMARY KEY (id),
  CONSTRAINT ck_control_id CHECK (id = 1),
  CONSTRAINT ck_control_reason CHECK (reason IN ('initial', 'operator', 'reset', 'deploy')),
  CONSTRAINT ck_control_last_reset_result
    CHECK (last_reset_result IN ('ok', 'drain_timeout', 'reseed_failed')));
INSERT INTO demo.control (id, paused, reason, changed_at) VALUES (1, true, 'initial', now());

CREATE TABLE demo.host_status (
  id smallint NOT NULL, live integer NOT NULL, in_flight integer NOT NULL,
  transcript_failures integer NOT NULL, reset_failures integer NOT NULL,
  started_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
  CONSTRAINT pk_host_status PRIMARY KEY (id),
  CONSTRAINT ck_host_status_id CHECK (id = 1),
  CONSTRAINT ck_host_status_live CHECK (live >= 0),
  CONSTRAINT ck_host_status_in_flight CHECK (in_flight >= 0),
  CONSTRAINT ck_host_status_transcript_failures CHECK (transcript_failures >= 0),
  CONSTRAINT ck_host_status_reset_failures CHECK (reset_failures >= 0));

CREATE TABLE demo.spend_day (
  day date NOT NULL, committed_micros bigint NOT NULL,
  CONSTRAINT pk_spend_day PRIMARY KEY (day),
  CONSTRAINT ck_spend_day_committed_micros CHECK (committed_micros >= 0));

CREATE TABLE demo.spend_request (
  id uuid NOT NULL, day date NOT NULL, model text NOT NULL, reserved_micros bigint NOT NULL,
  cost_micros bigint, input_tokens integer, output_tokens integer,
  cache_creation_input_tokens integer, cache_read_input_tokens integer, outcome text NOT NULL,
  created_at timestamptz NOT NULL, settled_at timestamptz,
  CONSTRAINT pk_spend_request PRIMARY KEY (id),
  CONSTRAINT ck_spend_request_reserved_micros CHECK (reserved_micros > 0),
  CONSTRAINT ck_spend_request_cost_micros CHECK (cost_micros >= 0),
  CONSTRAINT ck_spend_request_input_tokens CHECK (input_tokens >= 0),
  CONSTRAINT ck_spend_request_output_tokens CHECK (output_tokens >= 0),
  CONSTRAINT ck_spend_request_cache_creation_input_tokens
    CHECK (cache_creation_input_tokens >= 0),
  CONSTRAINT ck_spend_request_cache_read_input_tokens CHECK (cache_read_input_tokens >= 0),
  CONSTRAINT ck_spend_request_settled CHECK ((cost_micros IS NULL) = (settled_at IS NULL)));

CREATE TABLE demo.counter (
  day date NOT NULL, kind text NOT NULL, subject bytea NOT NULL, count integer NOT NULL,
  CONSTRAINT pk_counter PRIMARY KEY (day, kind, subject),
  CONSTRAINT ck_counter_count CHECK (count > 0));

CREATE TABLE demo.transcript (
  conversation_ref uuid NOT NULL, session_hash bytea NOT NULL, notice_version integer NOT NULL,
  brain_conversation_id uuid NOT NULL, started_at timestamptz NOT NULL,
  CONSTRAINT pk_transcript PRIMARY KEY (conversation_ref),
  CONSTRAINT ck_transcript_notice_version CHECK (notice_version > 0));

CREATE TABLE demo.transcript_event (
  conversation_ref uuid NOT NULL, seq integer NOT NULL, kind text NOT NULL,
  body jsonb NOT NULL, at timestamptz NOT NULL,
  CONSTRAINT pk_transcript_event PRIMARY KEY (conversation_ref, seq),
  CONSTRAINT fk_transcript_event_conversation_ref FOREIGN KEY (conversation_ref)
    REFERENCES demo.transcript (conversation_ref) ON DELETE CASCADE,
  CONSTRAINT ck_transcript_event_kind
    CHECK (kind IN ('customer_text', 'event', 'usage', 'error')),
  CONSTRAINT ck_transcript_event_seq CHECK (seq >= 0));

GRANT SELECT, UPDATE ON demo.control TO dale_app;
GRANT SELECT, INSERT, UPDATE ON demo.host_status, demo.spend_day, demo.spend_request
  TO dale_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON demo.counter TO dale_app;
GRANT SELECT, INSERT, DELETE ON demo.transcript, demo.transcript_event TO dale_app;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    raise NotImplementedError("forward-only migration: rebuild the database instead")
