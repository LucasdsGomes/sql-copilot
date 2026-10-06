---
name: sql-guardrails
description: Rules and checklist for writing, reviewing or changing SQL in the SQL Copilot project. Use when writing a query for the sales database, reviewing LLM-generated SQL, editing the validator (security/validator.py), the prompts (agent/prompts.py) or the DB layer (db/connection.py), or adding tables or columns that may hold sensitive data.
---

# SQL guardrails (SQL Copilot)

The agent lets an LLM write SQL for a real database, so the SQL is **untrusted input**. Security
does not depend on the model behaving: every query passes `validate_sql()` and runs on a read-only
connection. Never weaken that chain without a test that explains why.

## Database (SQLite, `data/sales.db`; source of truth: `src/sql_copilot/db/seed.py`)
- `customers(id, name, email, city, created_at)` - `email` is **restricted** (personal data)
- `products(id, name, category, price)`
- `orders(id, customer_id, order_date, status)` - status: paid, shipped, delivered, cancelled
- `order_items(id, order_id, product_id, quantity, unit_price)`
- Dates are ISO text (`YYYY-MM-DD`). Revenue = `SUM(quantity * unit_price)`; exclude `cancelled`
  orders unless asked otherwise.

## Query rules
1. One statement, `SELECT` (or `UNION` of selects) only. A CTE (`WITH`) is fine.
2. Only the four tables above. No `sqlite_*`, no `pragma_*`, no `schema.table`, no `VALUES`.
3. Never reference `email`, and never `SELECT *` (or `t.*`) on a query touching `customers`:
   list the columns. `COUNT(*)` is fine.
4. No `WITH RECURSIVE`, and a CTE must not be named like a real table or start with `sqlite_`.
5. Blocked functions: `load_extension`, `readfile`, `writefile`, `edit`, `fts3_tokenizer`,
   `zeroblob`, `randomblob`, `sqlite_version`, `sqlite_source_id`, `changes`, `total_changes`,
   `last_insert_rowid` and the `sqlite_compileoption_*` family.
6. A `LIMIT` is always enforced (default 100). Larger or non-literal limits are replaced, not run.
7. `date('now')` is allowed; relative-date questions need it.

## Verify, don't guess
Check any query with the real validator before relying on it:
```
.venv\Scripts\python scripts/check_sql.py "SELECT city, COUNT(*) FROM customers GROUP BY city"
```
It prints `SAFE: <normalised SQL>` or `REJECTED: <reason>` (exit code 1).

## When changing security code
- The policy is **deny by default**. Prefer rejecting over cleverly rewriting.
- Add a test first: attacks go in `tests/test_validator.py`; findings from a review go in
  `tests/test_redteam.py` (fixed ones as "must be rejected", harmless ones as "allowed on purpose"
  with the reason, so nobody "fixes" them later).
- Check by **node type**, not only by name: sqlglot maps `sqlite_version()` to `CurrentVersion`,
  so a name blocklist alone missed it.
- Reproduce a reported bypass against the real database before fixing; many reports are false
  positives (e.g. `LIMIT (SELECT 1000)` is replaced before it can run).
- Keep the DB layer's own protections (read-only mode, 5 s timeout, 1 MB value cap) even if the
  validator "already covers it": they are the last line of defence.
- Run `.venv\Scripts\python -m pytest -q` and `.venv\Scripts\python -m ruff check .`.

## Adding a table or column
- Add a table: put it in `DEFAULT_ALLOWED_TABLES` (validator.py) and in `seed.py`. Default is
  denied, so forgetting this fails safe.
- Sensitive column (PII, secrets): add it to `DEFAULT_BLOCKED_COLUMNS` and its table to
  `sensitive_tables`. `describe_schema()` then hides it from the LLM automatically.
- Add attack tests for the new column (direct, aliased, in a subquery, via `UNION`, via `*`).

## Prompt-injection stance
The user's question is data, not instructions (see `agent/prompts.py`). Do not rely on the prompt
for safety: the tests simulate an LLM that fully obeys an attacker and assert the query is refused
before it reaches the database and before the second LLM call.
