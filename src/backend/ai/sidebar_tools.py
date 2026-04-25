"""Sidebar SQLite tools for the stateless operator copilot."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import dspy

import backend.database as database_module

logger = logging.getLogger(__name__)

MAX_SQL_ROWS = 50
READONLY_SQL_PREFIXES = ("select", "with", "pragma", "explain")


def resolve_sqlite_database_path() -> Path:
    """Resolve the active SQLite file path from the configured database URL."""
    database_url = str(database_module.DATABASE_URL or "").strip()
    sqlite_prefix = "sqlite:///"
    if not database_url.startswith(sqlite_prefix):
        raise ValueError("Sidebar assistant only supports SQLite databases.")
    db_path = Path(database_url[len(sqlite_prefix) :]).expanduser()
    return db_path if db_path.is_absolute() else Path.cwd() / db_path


def normalize_readonly_query(query: str) -> str:
    """Normalize one SQL query before execution."""
    normalized = str(query or "").strip()
    if normalized.endswith(";"):
        normalized = normalized[:-1].strip()
    return normalized


def ensure_readonly_query(query: str) -> str:
    """Reject obviously non-read-only SQL before executing it."""
    normalized = normalize_readonly_query(query)
    if not normalized:
        raise ValueError("Query cannot be empty.")
    lowered = normalized.lower()
    if not lowered.startswith(READONLY_SQL_PREFIXES):
        raise ValueError(
            "Only read-only SQLite statements are allowed. Use SELECT, WITH, PRAGMA, or EXPLAIN."
        )
    return normalized


def serialize_sqlite_value(value: Any) -> Any:
    """Convert SQLite values into JSON-safe payloads."""
    if isinstance(value, bytes):
        return value.hex()
    return value


def quote_sqlite_identifier(identifier: str) -> str:
    """Quote one SQLite identifier for deterministic introspection queries."""
    return '"' + str(identifier or "").replace('"', '""') + '"'


def quote_sqlite_literal(value: str) -> str:
    """Quote one SQLite string literal for PRAGMA introspection."""
    return "'" + str(value or "").replace("'", "''") + "'"


def connect_readonly_sqlite(db_path: Path) -> sqlite3.Connection:
    """Open the configured SQLite database in read-only mode."""
    readonly_uri = f"{db_path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(readonly_uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def execute_sql_fetch(query: str, *, max_rows: int = MAX_SQL_ROWS) -> dict[str, Any]:
    """Execute one read-only SQLite statement and return a compact payload."""
    readonly_query = ensure_readonly_query(query)
    logger.info("Sidebar SQL: %s", readonly_query)
    db_path = resolve_sqlite_database_path()
    if not db_path.exists():
        return {
            "query": readonly_query,
            "error": f"Database file not found at {db_path}",
            "columns": [],
            "rows": [],
            "truncated": False,
        }

    try:
        with connect_readonly_sqlite(db_path) as connection:
            cursor = connection.execute(readonly_query)
            raw_rows = cursor.fetchmany(max_rows + 1)
            columns = [description[0] for description in cursor.description or []]
    except sqlite3.Error as exc:
        return {
            "query": readonly_query,
            "error": f"SQLite error: {exc}",
            "columns": [],
            "rows": [],
            "truncated": False,
        }

    truncated = len(raw_rows) > max_rows
    visible_rows = raw_rows[:max_rows]
    rows = [
        {column: serialize_sqlite_value(row[column]) for column in columns}
        for row in visible_rows
    ]
    return {
        "query": readonly_query,
        "columns": columns,
        "rows": rows,
        "returned_rows": len(rows),
        "truncated": truncated,
    }


def run_readonly_sql(query: str, max_rows: int = MAX_SQL_ROWS) -> str:
    """Execute one read-only SQLite query against the active Konecta database."""
    payload = execute_sql_fetch(query, max_rows=max(1, min(int(max_rows), 200)))
    return json.dumps(payload, ensure_ascii=True, indent=2)


def list_sqlite_tables(connection: sqlite3.Connection) -> list[str]:
    """Return user-defined SQLite table names in deterministic order."""
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(row["name"]) for row in rows]


def describe_table_columns(connection: sqlite3.Connection, table_name: str) -> str:
    """Return one compact schema line for the given SQLite table."""
    rows = connection.execute(
        f"PRAGMA table_info({quote_sqlite_literal(table_name)})"
    ).fetchall()
    columns = []
    for row in rows:
        column_text = row["name"]
        if row["type"]:
            column_text += f" {row['type']}"
        if row["pk"]:
            column_text += " PRIMARY KEY"
        if row["notnull"]:
            column_text += " NOT NULL"
        columns.append(column_text)
    return ", ".join(columns) or "(no columns detected)"


def describe_table_row_count(connection: sqlite3.Connection, table_name: str) -> int:
    """Return the number of rows in one SQLite table."""
    row = connection.execute(
        f"SELECT COUNT(*) AS total_rows FROM {quote_sqlite_identifier(table_name)}"
    ).fetchone()
    return int(row["total_rows"]) if row else 0


def describe_detected_joins(connection: sqlite3.Connection, table_names: list[str]) -> list[str]:
    """Return join hints discovered from SQLite foreign keys."""
    join_lines: list[str] = []
    for table_name in table_names:
        rows = connection.execute(
            f"PRAGMA foreign_key_list({quote_sqlite_literal(table_name)})"
        ).fetchall()
        for row in rows:
            join_lines.append(
                f"- {table_name}.{row['from']} = {row['table']}.{row['to']}"
            )
    return join_lines


def describe_konecta_database() -> str:
    """Describe the active SQLite schema, row counts, and detected joins."""
    db_path = resolve_sqlite_database_path()
    if not db_path.exists():
        return f"Database file not found at {db_path}"

    try:
        with connect_readonly_sqlite(db_path) as connection:
            table_names = list_sqlite_tables(connection)
            if not table_names:
                return f"Database path: {db_path}\nNo user tables found."

            sections = [f"Database path: {db_path}", "Tables:"]
            for table_name in table_names:
                row_count = describe_table_row_count(connection, table_name)
                column_text = describe_table_columns(connection, table_name)
                sections.append(f"- {table_name} (rows={row_count}): {column_text}")

            join_lines = describe_detected_joins(connection, table_names)
    except sqlite3.Error as exc:
        logger.warning("Sidebar assistant schema introspection failed: %s", exc)
        return f"SQLite error while describing database: {exc}"

    if join_lines:
        sections.append("Detected joins:")
        sections.extend(join_lines)
    else:
        sections.append("Detected joins: none declared via SQLite foreign keys.")
    return "\n".join(sections)


def build_sidebar_assistant_tools() -> list[dspy.Tool]:
    """Build the DSPy tools for the sidebar database assistant."""
    return [
        dspy.Tool(
            name="describe_konecta_database",
            desc=(
                "Returns the active SQLite schema discovered from the live database, including "
                "table names, columns, row counts, and detected foreign-key joins."
            ),
            func=describe_konecta_database,
        ),
        dspy.Tool(
            name="run_readonly_sql",
            desc=(
                "Executes exactly one read-only SQLite statement against the active Konecta database. "
                "Only SELECT, WITH, PRAGMA, or EXPLAIN are allowed. Use this for counts, comparisons, "
                "lists, company detail lookups, or transcript inspection."
            ),
            func=run_readonly_sql,
        ),
    ]
