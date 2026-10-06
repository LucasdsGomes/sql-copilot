"""The 3-step pipeline: question -> SQL (LLM) -> validate + run -> answer (LLM)."""

import re
import sqlite3
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser

from sql_copilot.agent.prompts import ANSWER_PROMPT, SQL_PROMPT
from sql_copilot.config import Settings
from sql_copilot.db.connection import run_query
from sql_copilot.db.schema import describe_schema
from sql_copilot.security.validator import UnsafeQueryError, ValidationPolicy, validate_sql

MAX_ROWS_FOR_SUMMARY = 20
MAX_QUESTION_LENGTH = 500


@dataclass
class Answer:
    question: str
    answer: str
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[tuple] | None = None
    refused_reason: str | None = None

    @property
    def refused(self) -> bool:
        return self.refused_reason is not None


def build_llm(settings: Settings) -> BaseChatModel:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env first.")
    from langchain_anthropic import ChatAnthropic  # imported lazily so tests need no key

    return ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        temperature=0,
        max_tokens=600,
        timeout=30,
        max_retries=2,
    )


def extract_sql(text: str) -> str:
    """Models sometimes wrap SQL in markdown fences despite instructions; strip them."""
    text = text.strip()
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else text).strip()


class SqlCopilot:
    def __init__(self, llm: BaseChatModel, db_path: str, policy: ValidationPolicy | None = None):
        self.db_path = db_path
        self.policy = policy or ValidationPolicy()
        self._schema = describe_schema(db_path, self.policy)
        parser = StrOutputParser()
        self._sql_chain = SQL_PROMPT | llm | parser
        self._answer_chain = ANSWER_PROMPT | llm | parser

    def ask(self, question: str) -> Answer:
        question = question.strip()
        if not question:
            return Answer(question, "Please ask a question.", refused_reason="empty question")
        if len(question) > MAX_QUESTION_LENGTH:
            return Answer(question, "Question is too long.", refused_reason="question too long")

        # 1. LLM writes SQL
        raw = self._sql_chain.invoke({"question": question, "schema": self._schema})

        # 2. Security gate: nothing the LLM wrote touches the database unchecked
        try:
            sql = validate_sql(extract_sql(raw), self.policy)
        except UnsafeQueryError as e:
            return Answer(
                question,
                "I can't run that query for security reasons.",
                sql=extract_sql(raw),
                refused_reason=str(e),
            )

        # 3. Execute on the read-only connection
        try:
            result = run_query(self.db_path, sql, self.policy.max_rows)
        except sqlite3.Error as e:
            return Answer(question, "The generated query failed to run.", sql=sql,
                          refused_reason=f"database error: {e}")

        # 4. LLM turns the rows into an answer
        table = _format_rows(result.columns, result.rows, result.truncated)
        text = self._answer_chain.invoke({"question": question, "sql": sql, "result": table})
        return Answer(question, text.strip(), sql=sql, columns=result.columns, rows=result.rows)


def _format_rows(columns: list[str], rows: list[tuple], truncated: bool) -> str:
    shown = rows[:MAX_ROWS_FOR_SUMMARY]
    lines = [" | ".join(columns)] + [" | ".join(str(v) for v in r) for r in shown]
    if truncated or len(rows) > len(shown):
        lines.append(f"(truncated: showing first {len(shown)} rows)")
    if not rows:
        lines.append("(no rows)")
    return "\n".join(lines)
