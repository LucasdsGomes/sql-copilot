"""Read-only access to the SQLite database: the last line of defence."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool


def get_readonly_connection(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}. Run scripts/seed_db.py first.")
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def run_query(db_path: str | Path, sql: str, max_rows: int = 100) -> QueryResult:
    """Run a query on a read-only connection and cap the number of rows returned."""
    conn = get_readonly_connection(db_path)
    try:
        cursor = conn.execute(sql)
        columns = [d[0] for d in cursor.description or []]
        rows = cursor.fetchmany(max_rows + 1)
    finally:
        conn.close()
    return QueryResult(columns=columns, rows=rows[:max_rows], truncated=len(rows) > max_rows)
