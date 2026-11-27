"""Revisions from 0006 on only add (DD46, G8): the previous image keeps working against the new
schema, so a rollback is a redeploy, never a downgrade, and no revision destroys demo data.

The lint reads each revision's code, not its prose: every string literal but the docstrings
(SQL comments removed), and every `op` call. It refuses a drop (DROP NOT NULL and DROP DEFAULT
only relax a column, so they pass), a rename, a type change, SET NOT NULL, a NOT NULL column
with no default (the previous image's INSERTs would fail with 23502), a REVOKE (except on a
schema the same revision creates), and a TRUNCATE, DELETE or UPDATE statement (a TRUNCATE
would reset the daily cap; a deleted control row would leave the demo paused for good). A new
constraint or unique index, which the previous image's writes may break, needs the line
`# additive-exception: <id>` naming a decision-log row (log D40); constraints written inside
the CREATE TABLE of a new table need nothing.

It is a review aid, not a security boundary: string concatenation, an aliased `op`, or SQL
read from a file or built at run time evade it. Every migration still needs a human review.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = sorted((ROOT / "migrations" / "versions").glob("*.py"))
FIRST_ADDITIVE = 6
LOGS = "".join(p.read_text() for p in sorted((ROOT / "openspec").rglob("decision-log.md")))
DECISIONS = frozenset(re.findall(r"^\| (D\d+) \|", LOGS, re.M))
FORBIDDEN_SQL = {
    "DROP": r"\bDROP\b(?!\s+(?:NOT\s+NULL|DEFAULT)\b)",
    "RENAME": r"\bRENAME\b",
    "ALTER ... TYPE": r"\bALTER\s+(?:COLUMN\s+)?[\w\"]+\s+(?:SET\s+DATA\s+)?TYPE\b",
    "SET NOT NULL": r"\bSET\s+NOT\s+NULL\b",
    "TRUNCATE": r"\bTRUNCATE\b(?!\s*(?:,|ON\b))",  # not a privilege name in a GRANT
    "DELETE": r"\bDELETE\s+FROM\b",
    "UPDATE": r"\bUPDATE\s+(?:ONLY\s+)?[\w.\"]+(?:\s+(?:AS\s+)?\w+)?\s+SET\b",
}
TABLE_CONSTRAINTS = r"CONSTRAINT|PRIMARY|UNIQUE|CHECK|FOREIGN|EXCLUDE"
ADD_COLUMN = rf"\bADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(?!(?:{TABLE_CONSTRAINTS}|VALUE)\b)"
CONSTRAINT_SQL = rf"\bADD\s+(?:{TABLE_CONSTRAINTS})\b|\bCREATE\s+UNIQUE\s+INDEX\b"
INLINE_CONSTRAINT = r"\b(?:CHECK|UNIQUE|REFERENCES|PRIMARY\s+KEY)\b"
FORBIDDEN_OPS = re.compile(r"(drop|rename)_\w+|alter_column|batch_alter_table")
CONSTRAINT_OPS = re.compile(r"create_(\w+_constraint|foreign_key|primary_key)")
MARKER = re.compile(r"^# additive-exception: (D\d+)$", re.M)


def _docstrings(tree: ast.Module) -> set[int]:
    nodes = [tree, *(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.ClassDef))]
    return {
        id(body[0].value)
        for body in (n.body for n in nodes)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
    }


def _clause(sql: str, start: int) -> str:
    """From `start` to the first comma or semicolon outside parentheses."""
    depth = 0
    for end, char in enumerate(sql[start:], start):
        depth += {"(": 1, ")": -1}.get(char, 0)
        if (depth == 0 and char in ",;") or depth < 0:
            return sql[start:end]
    return sql[start:]


def _sql_findings(sql: str) -> list[str]:
    found = [name for name, rule in FORBIDDEN_SQL.items() if re.search(rule, sql, re.I)]
    created = {s.lower() for s in re.findall(r"\bCREATE\s+SCHEMA\s+(\w+)", sql, re.I)}
    for revoke in re.finditer(r"\bREVOKE\b[^;]*", sql, re.I):
        schema = re.search(r"\bON\s+SCHEMA\s+(\w+)\s+FROM\b", revoke[0], re.I)
        if not schema or schema[1].lower() not in created:
            found.append("REVOKE")
    for column in re.finditer(ADD_COLUMN, sql, re.I):
        clause = _clause(sql, column.end())
        if re.search(r"\bNOT\s+NULL\b", clause, re.I) and not re.search(
            r"\bDEFAULT\b", clause, re.I
        ):
            found.append("NOT NULL column")
        if re.search(INLINE_CONSTRAINT, clause, re.I):
            found.append("constraint")
    return found + ["constraint"] * len(re.findall(CONSTRAINT_SQL, sql, re.I))


def _keyword(call: ast.Call, name: str, default: object) -> object:
    """A keyword argument's literal value; `default` when absent, the node when not literal."""
    node = next((k.value for k in call.keywords if k.arg == name), None)
    return default if node is None else getattr(node, "value", node)


def _op_findings(call: ast.Call, name: str) -> list[str]:
    if FORBIDDEN_OPS.fullmatch(name):
        return [f"op.{name}"]
    if CONSTRAINT_OPS.fullmatch(name) or (name == "create_index" and _keyword(call, "unique", 0)):
        return ["constraint"]
    if name == "add_column":
        columns = [a for a in call.args if isinstance(a, ast.Call)]
        return [
            "NOT NULL column"
            for c in columns
            if _keyword(c, "nullable", True) is False
            and _keyword(c, "server_default", None) is None
        ]
    return []


def violations(source: str, decisions: frozenset[str] = DECISIONS) -> list[str]:
    """What makes a revision non-additive; empty when it only adds."""
    tree = ast.parse(source)
    prose = _docstrings(tree)
    strings = [
        re.sub(r"--[^\n]*", "", node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose
    ]
    found = _sql_findings("\n;\n".join(strings))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
        ):
            found += _op_findings(node, node.func.attr)
    excepted = {m for m in MARKER.findall(source) if m in decisions}
    return [f for f in found if not (f == "constraint" and excepted)]


def _revision(ddl: str = "", call: str = "op.execute(DDL)", marker: str = "") -> str:
    return (
        '"""A later revision. Its prose may say DROP or SET NOT NULL: only code counts."""\n'
        f"import sqlalchemy as sa\nfrom alembic import op\n{marker}\n"
        'revision = "0007"\ndown_revision = "0006"\n'
        f'DDL = """\n-- comments do not count either: DROP\n{ddl}\n"""\n\n\n'
        f"def upgrade() -> None:\n    {call}\n"
    )


ADDITIVE = [p for p in VERSIONS if int(p.name[:4]) >= FIRST_ADDITIVE]


def test_every_revision_is_numbered_so_none_escapes_the_lint() -> None:
    assert [p.name for p in VERSIONS if not re.match(r"\d{4}_\w+\.py$", p.name)] == []
    assert "0006_demo_schema.py" in [p.name for p in ADDITIVE]


@pytest.mark.parametrize("path", ADDITIVE, ids=lambda p: p.stem)
def test_real_revisions_from_0006_only_add(path: Path) -> None:
    assert violations(path.read_text()) == []


@pytest.mark.parametrize(
    ("ddl", "rule"),
    [
        ("DROP TABLE demo.counter;", "DROP"),
        ("ALTER TABLE demo.counter DROP COLUMN count;", "DROP"),
        ("ALTER TABLE demo.counter RENAME COLUMN count TO n;", "RENAME"),
        ("ALTER TABLE demo.counter ALTER COLUMN count TYPE smallint;", "ALTER ... TYPE"),
        ("ALTER TABLE demo.counter ALTER count SET DATA TYPE smallint;", "ALTER ... TYPE"),
        ("ALTER TABLE demo.spend_request ALTER COLUMN cost_micros SET NOT NULL;", "SET NOT NULL"),
        ("ALTER TABLE demo.counter ADD COLUMN note text NOT NULL;", "NOT NULL column"),
        ("REVOKE SELECT ON demo.control FROM dale_app;", "REVOKE"),
        ("REVOKE USAGE ON SCHEMA demo FROM dale_app;", "REVOKE"),
        ("TRUNCATE demo.spend_day;", "TRUNCATE"),
        ("DELETE FROM demo.control;", "DELETE"),
        ("UPDATE demo.control SET paused = false;", "UPDATE"),
        ("ALTER TABLE demo.counter ADD CONSTRAINT ck_counter_cap CHECK (count < 9);", "constraint"),
        ("ALTER TABLE demo.counter ADD COLUMN cap int CHECK (cap > 0);", "constraint"),
        ("CREATE UNIQUE INDEX ix_counter_kind ON demo.counter (kind);", "constraint"),
    ],
)
def test_a_non_additive_ddl_revision_is_refused(ddl: str, rule: str) -> None:
    assert violations(_revision(ddl)) == [rule]


@pytest.mark.parametrize(
    ("call", "rule"),
    [
        ('op.drop_column("counter", "count", schema="demo")', "op.drop_column"),
        ('op.rename_table("counter", "counts", schema="demo")', "op.rename_table"),
        ('op.alter_column("counter", "count", nullable=False, schema="demo")', "op.alter_column"),
        ('op.add_column("counter", sa.Column("n", sa.Integer, nullable=False))', "NOT NULL column"),
        ('op.execute("REVOKE ALL ON demo.control FROM dale_app")', "REVOKE"),
        ('op.create_check_constraint("cap", "counter", "count < 9")', "constraint"),
        ('op.create_unique_constraint("uq", "counter", ["kind"])', "constraint"),
        ('op.create_foreign_key("fk", "counter", "transcript", ["r"], ["r"])', "constraint"),
        ('op.create_index("ix", "counter", ["kind"], unique=True)', "constraint"),
    ],
)
def test_a_non_additive_op_call_is_refused(call: str, rule: str) -> None:
    assert violations(_revision(call=call)) == [rule]


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE demo.later (id int NOT NULL, ref uuid NOT NULL, CONSTRAINT pk_later"
        " PRIMARY KEY (id), CONSTRAINT ck_later_id CHECK (id > 0), CONSTRAINT fk_later_ref"
        " FOREIGN KEY (ref) REFERENCES demo.transcript ON DELETE CASCADE ON UPDATE SET NULL);"
        " GRANT SELECT, UPDATE, DELETE ON demo.later TO dale_app;",
        "ALTER TABLE demo.counter ADD COLUMN note text, ADD COLUMN n int NOT NULL DEFAULT 0;",
        "ALTER TABLE demo.spend_request ALTER COLUMN model DROP NOT NULL;",
        "ALTER TABLE demo.spend_request ALTER COLUMN outcome DROP DEFAULT;",
        "CREATE SCHEMA later; REVOKE ALL ON SCHEMA later FROM PUBLIC;",
        "CREATE INDEX ix_counter_kind ON demo.counter (kind);",
    ],
)
def test_an_additive_ddl_revision_passes(ddl: str) -> None:
    assert violations(_revision(ddl)) == []


@pytest.mark.parametrize(
    "call",
    [
        'op.add_column("counter", sa.Column("n", sa.Integer, nullable=False, server_default="0"))',
        'op.create_table("later", sa.Column("id", sa.Integer), sa.CheckConstraint("id > 0"))',
    ],
)
def test_an_additive_op_call_passes(call: str) -> None:
    assert violations(_revision(call=call)) == []


def test_a_constraint_passes_only_with_a_marker_naming_a_logged_decision() -> None:
    ddl = "ALTER TABLE demo.counter ADD CONSTRAINT ck_counter_cap CHECK (count < 9);"
    marked = _revision(ddl, marker="# additive-exception: D40")
    assert violations(marked, frozenset({"D40"})) == []
    assert violations(marked, frozenset({"D41"})) == ["constraint"]
    assert violations(_revision(ddl, marker="# additive-exception D40")) == ["constraint"]
    assert violations(
        _revision("DROP TABLE demo.counter;", marker="# additive-exception: D38")
    ) == ["DROP"]
    assert "D38" in DECISIONS  # read from the real decision logs
