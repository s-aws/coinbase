"""Schema smoke test for runtime-reconciler SQL.

These tests guard against the exact failure mode that shipped the
phantom ``order_child`` reference: a hand-written SQL string that
references a table or column that does not actually exist in the
schema. Mocked-DB unit tests cannot catch this — they let any SQL
through. We catch it by *parsing* the SQL strings out of the
reconciler module and verifying every ``(table, column)`` referenced
appears in a ``CREATE TABLE`` block in :mod:`database.order`.

Why static analysis instead of a live DB:

* PostgreSQL-specific DDL (``SERIAL``, ``JSONB``, etc.) cannot run
  against SQLite, and standing up Postgres in CI is heavier than the
  bug we're guarding against warrants.
* The bug class is *typos and stale assumptions*. A grep-based check
  is sufficient and runs in milliseconds.

If the parser misses a future SQL pattern, prefer extending the
regexes here over silencing the test.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Set, Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RECONCILER_PATH = REPO_ROOT / "core" / "startup_reconciler.py"
PERIODIC_PATH = REPO_ROOT / "core" / "periodic_reconciler.py"
SCHEMA_PATH = REPO_ROOT / "database" / "order.py"


# ---------------------------------------------------------------------------
# Schema extraction (database/order.py -> {table: {columns}})
# ---------------------------------------------------------------------------


_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
_ALTER_ADD_COLUMN_RE = re.compile(
    r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+(\w+)",
    re.IGNORECASE,
)
# A column definition is a leading identifier (after whitespace/comma)
# followed by a type token. Skip table-level constraints like
# ``CONSTRAINT``, ``PRIMARY KEY``, ``UNIQUE``, ``CHECK``, ``FOREIGN KEY``.
_COLUMN_LINE_RE = re.compile(
    r"^\s*(?!CONSTRAINT|PRIMARY\s+KEY|UNIQUE|CHECK|FOREIGN\s+KEY|--)"
    r"([A-Za-z_][A-Za-z0-9_]*)\s+[A-Za-z]",
    re.IGNORECASE | re.MULTILINE,
)


def _build_schema() -> Dict[str, Set[str]]:
    """Return ``{table_name: {column_name, ...}}`` parsed from the schema file."""
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    schema: Dict[str, Set[str]] = {}

    for match in _CREATE_TABLE_RE.finditer(text):
        table = match.group(1).lower()
        body = match.group(2)
        cols = {m.group(1).lower() for m in _COLUMN_LINE_RE.finditer(body)}
        # If the same table is created in multiple branches (we have
        # two ``fill_ledger`` definitions for back-compat), union the
        # column sets so either branch is acceptable.
        schema.setdefault(table, set()).update(cols)

    for match in _ALTER_ADD_COLUMN_RE.finditer(text):
        table = match.group(1).lower()
        col = match.group(2).lower()
        schema.setdefault(table, set()).add(col)

    return schema


# ---------------------------------------------------------------------------
# SQL extraction (core/*.py -> [(table, [columns])])
# ---------------------------------------------------------------------------


_SELECT_FROM_RE = re.compile(
    r"SELECT\s+(.+?)\s+FROM\s+(\w+)",
    re.IGNORECASE | re.DOTALL,
)
_UPDATE_SET_RE = re.compile(
    r"UPDATE\s+(\w+)\s+SET\s+(\w+)",
    re.IGNORECASE,
)
_INSERT_INTO_RE = re.compile(
    r"INSERT\s+INTO\s+(\w+)\s*\(([^)]*)\)",
    re.IGNORECASE,
)


def _split_select_columns(select_clause: str) -> Set[str]:
    """Return identifier names from a SELECT clause; '*' yields empty set."""
    cleaned = select_clause.strip()
    if cleaned == "*":
        return set()
    cols: Set[str] = set()
    for part in cleaned.split(","):
        token = part.strip().split()[0]  # strip "AS alias", trailing whitespace
        # qualified.column -> column
        if "." in token:
            token = token.split(".")[-1]
        # function calls like COUNT(x) -> skip; we only want bare identifiers
        if "(" in token or token == "*":
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            cols.add(token.lower())
    return cols


def _extract_sql_references(source: str) -> Set[Tuple[str, str]]:
    """Return ``{(table, column), ...}`` referenced by SQL in the source."""
    refs: Set[Tuple[str, str]] = set()

    for select_clause, table in _SELECT_FROM_RE.findall(source):
        for col in _split_select_columns(select_clause):
            refs.add((table.lower(), col))

    for table, col in _UPDATE_SET_RE.findall(source):
        refs.add((table.lower(), col.lower()))

    for table, col_list in _INSERT_INTO_RE.findall(source):
        for raw in col_list.split(","):
            col = raw.strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", col):
                refs.add((table.lower(), col.lower()))

    return refs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema() -> Dict[str, Set[str]]:
    s = _build_schema()
    assert s, "Failed to parse any tables from database/order.py"
    return s


@pytest.fixture(scope="module")
def reconciler_sql_refs() -> Set[Tuple[str, str]]:
    refs = _extract_sql_references(RECONCILER_PATH.read_text(encoding="utf-8"))
    assert refs, "Failed to extract any SQL refs from core/startup_reconciler.py"
    return refs


class TestSchemaParser:
    """Sanity checks on the parsing helpers themselves."""

    @pytest.mark.regression
    def test_schema_includes_known_tables(self, schema):
        # Anchor the parser on tables we know exist; if any of these
        # disappear from the parsed output, the parser regressed.
        for required in ("order_parent", "fill_ledger", "stealth_orders"):
            assert required in schema, (
                f"Schema parser failed to discover {required!r}; "
                f"got tables: {sorted(schema)}"
            )

    @pytest.mark.regression
    def test_schema_parser_does_not_invent_tables(self, schema):
        # The phantom we shipped. Belt-and-braces: if this ever
        # appears, either the production schema added it (in which
        # case great, update the assertion) or the parser is wrong.
        assert "order_child" not in schema

    @pytest.mark.regression
    def test_extracts_known_columns(self, schema):
        assert "client_order_id" in schema["order_parent"]
        assert "status" in schema["order_parent"]
        assert "exchange_entry_id" in schema["fill_ledger"]


class TestReconcilerSqlMatchesSchema:
    """The actual guard: every SQL ref in the reconciler must exist."""

    @pytest.mark.regression
    def test_every_table_exists(self, reconciler_sql_refs, schema):
        bad_tables = {
            table for table, _col in reconciler_sql_refs if table not in schema
        }
        assert not bad_tables, (
            f"Reconciler references unknown tables: {sorted(bad_tables)}. "
            f"Known tables: {sorted(schema)}"
        )

    @pytest.mark.regression
    def test_every_column_exists(self, reconciler_sql_refs, schema):
        bad_cols = []
        for table, col in sorted(reconciler_sql_refs):
            if table not in schema:
                continue  # already reported by the table test
            if col not in schema[table]:
                bad_cols.append(f"{table}.{col}")
        assert not bad_cols, (
            f"Reconciler references unknown columns: {bad_cols}"
        )

    @pytest.mark.regression
    def test_periodic_reconciler_has_no_phantom_sql(self, schema):
        # The periodic reconciler currently delegates to
        # run_startup_reconciliation and contains no direct SQL, but
        # if that ever changes we want the same guard.
        refs = _extract_sql_references(
            PERIODIC_PATH.read_text(encoding="utf-8")
        )
        bad = [
            f"{t}.{c}"
            for t, c in sorted(refs)
            if t not in schema or c not in schema.get(t, set())
        ]
        assert not bad, (
            f"PeriodicReconciler references unknown schema: {bad}"
        )
