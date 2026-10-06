"""Read-only access to the SQLite database: the last line of defence."""

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_S = 5.0
MAX_VALUE_BYTES = 1_000_000
_PROGRESS_STEPS = 10_000  # SQLite VM instructions between deadline checks


class QueryTimeoutError(sqlite3.OperationalError):
    """The query ran longer than the allowed time budget and was aborted."""


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
    # Cap any single string/blob (blocks memory bombs such as printf('%1000000000d', 1)).
    conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_VALUE_BYTES)
    return conn


def run_query(
    db_path: str | Path, sql: str, max_rows: int = 100, timeout_s: float = DEFAULT_TIMEOUT_S
) -> QueryResult:
    """Run a query on a read-only connection, capped in rows returned and in running time."""
    conn = get_readonly_connection(db_path)
    try:
        deadline = time.monotonic() + timeout_s
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), _PROGRESS_STEPS)
        try:
            cursor = conn.execute(sql)
            columns = [d[0] for d in cursor.description or []]
            rows = cursor.fetchmany(max_rows + 1)
        except sqlite3.OperationalError as e:
            if "interrupted" in str(e).lower():
                raise QueryTimeoutError(f"Query exceeded {timeout_s:g}s and was aborted.") from e
            raise
    finally:
        conn.close()
    return QueryResult(columns=columns, rows=rows[:max_rows], truncated=len(rows) > max_rows)
