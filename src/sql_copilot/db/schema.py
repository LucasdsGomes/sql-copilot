"""Builds the schema description shown to the LLM, hiding anything the policy blocks."""

from pathlib import Path

from sql_copilot.db.connection import get_readonly_connection
from sql_copilot.security.validator import ValidationPolicy


def describe_schema(db_path: str | Path, policy: ValidationPolicy | None = None) -> str:
    policy = policy or ValidationPolicy()
    conn = get_readonly_connection(db_path)
    try:
        lines = []
        for table in sorted(policy.allowed_tables):
            cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            visible = [f"{c[1]} {c[2]}" for c in cols if c[1].lower() not in policy.blocked_columns]
            if visible:
                lines.append(f"- {table}({', '.join(visible)})")
    finally:
        conn.close()
    return "\n".join(lines)
