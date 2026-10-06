"""SQL guardrails: every query the LLM writes must pass through validate_sql().

Policy (deny by default):
  * exactly one statement, and it must be a SELECT (or UNION of SELECTs)
  * only allow-listed tables, never schema-qualified, never table-valued functions
  * sensitive columns (e.g. email) can't be referenced, nor reached through `SELECT *`
  * dangerous SQLite functions are blocked
  * a LIMIT is always enforced

The query is re-generated from the parsed tree, so comments and odd formatting
that could hide intent never reach the database.
"""

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

DEFAULT_ALLOWED_TABLES = frozenset({"customers", "products", "orders", "order_items"})
DEFAULT_BLOCKED_COLUMNS = frozenset({"email"})
BLOCKED_FUNCTIONS = frozenset({
    "load_extension", "readfile", "writefile", "edit", "fts3_tokenizer",
    "zeroblob", "randomblob",  # memory-exhaustion vectors
    # environment / connection introspection
    "sqlite_version", "sqlite_source_id", "sqlite_compileoption_used",
    "sqlite_compileoption_get", "changes", "total_changes", "last_insert_rowid",
})
MAX_QUERY_LENGTH = 2000


class UnsafeQueryError(ValueError):
    """Raised when a query violates the security policy."""


@dataclass(frozen=True)
class ValidationPolicy:
    allowed_tables: frozenset[str] = DEFAULT_ALLOWED_TABLES
    blocked_columns: frozenset[str] = DEFAULT_BLOCKED_COLUMNS
    sensitive_tables: frozenset[str] = field(default_factory=lambda: frozenset({"customers"}))
    max_rows: int = 100


def validate_sql(sql: str, policy: ValidationPolicy | None = None) -> str:
    """Return a safe, LIMIT-bounded version of `sql`, or raise UnsafeQueryError."""
    policy = policy or ValidationPolicy()

    if not sql or not sql.strip():
        raise UnsafeQueryError("Empty query.")
    if len(sql) > MAX_QUERY_LENGTH:
        raise UnsafeQueryError("Query is too long.")

    try:
        statements = [s for s in sqlglot.parse(sql, dialect="sqlite") if s is not None]
    except SqlglotError as e:
        raise UnsafeQueryError(f"Query could not be parsed: {e}") from e

    if len(statements) != 1:
        raise UnsafeQueryError("Only a single statement is allowed.")
    root = statements[0]

    if not isinstance(root, exp.Select | exp.SetOperation):
        raise UnsafeQueryError(f"Only SELECT queries are allowed (got {type(root).__name__}).")

    _check_structure(root, policy)
    _check_tables(root, policy)
    _check_functions(root)
    _check_columns(root, policy)
    _enforce_limit(root, policy.max_rows)

    return root.sql(dialect="sqlite", comments=False)


def _check_structure(root: exp.Expression, policy: ValidationPolicy) -> None:
    """Constructs with no legitimate use here; rejecting them keeps the rest simple."""
    for with_ in root.find_all(exp.With):
        if with_.args.get("recursive"):
            raise UnsafeQueryError("Recursive queries are not allowed.")
    for cte in root.find_all(exp.CTE):
        name = cte.alias_or_name.lower()
        # A CTE named like a real table would make table checks ambiguous.
        if name in policy.allowed_tables or name.startswith("sqlite_"):
            raise UnsafeQueryError(f"CTE name '{cte.alias_or_name}' is reserved.")
    if root.find(exp.Values):
        raise UnsafeQueryError("VALUES lists are not allowed.")


def _check_tables(root: exp.Expression, policy: ValidationPolicy) -> None:
    cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    for table in root.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise UnsafeQueryError("Table-valued functions are not allowed.")
        if table.db or table.catalog:
            raise UnsafeQueryError("Schema-qualified tables are not allowed.")
        name = table.name.lower()
        if name in cte_names:
            continue
        if name not in policy.allowed_tables:
            raise UnsafeQueryError(f"Table '{table.name}' is not allowed.")


def _check_functions(root: exp.Expression) -> None:
    for func in root.find_all(exp.Func):
        # sqlglot maps sqlite_version() to its own node type, so a name check alone misses it.
        if isinstance(func, exp.CurrentVersion):
            raise UnsafeQueryError("Function 'sqlite_version' is not allowed.")
        name =func.sql_name().lower() if not isinstance(func, exp.Anonymous) else func.name.lower()
        if name in BLOCKED_FUNCTIONS:
            raise UnsafeQueryError(f"Function '{name}' is not allowed.")


def _check_columns(root: exp.Expression, policy: ValidationPolicy) -> None:
    for col in root.find_all(exp.Column):
        if isinstance(col.this, exp.Star):
            continue  # handled by the star check below
        if col.name.lower() in policy.blocked_columns:
            raise UnsafeQueryError(f"Column '{col.name}' is restricted (sensitive data).")

    touches_sensitive = any(
        t.name.lower() in policy.sensitive_tables for t in root.find_all(exp.Table)
    )
    if not touches_sensitive:
        return
    for star in root.find_all(exp.Star):
        if isinstance(star.parent, exp.Count):
            continue  # COUNT(*) exposes no column values
        raise UnsafeQueryError(
            "SELECT * is not allowed on tables with sensitive columns; list the columns you need."
        )


def _enforce_limit(root: exp.Expression, max_rows: int) -> None:
    limit = root.args.get("limit")
    if limit is not None:
        value = limit.expression
        if isinstance(value, exp.Literal) and value.is_int and int(value.this) <= max_rows:
            return
    root.set("limit", None)
    root.limit(max_rows, copy=False)
