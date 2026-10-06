# SQL Copilot - agent guide

Text-to-SQL agent: natural-language question -> LangChain (Claude) writes SQL -> security validator
-> read-only SQLite -> LLM summarises. Served through a FastAPI API (in progress).
Portfolio project; code, comments, docs and commits are in **English**.

## Commands (Windows, venv at `.venv`)
```
.venv\Scripts\python -m pytest -q          # all tests (no API key, no network, no cost)
.venv\Scripts\python -m ruff check .       # lint (line length 100)
.venv\Scripts\python scripts/seed_db.py    # (re)create data/sales.db
.venv\Scripts\python scripts/ask.py "..."  # real Anthropic call (costs money; ask the user first)
```

## Layout
- `src/sql_copilot/config.py` - settings from `.env` (pydantic-settings)
- `src/sql_copilot/db/` - `seed.py` (fake data), `connection.py` (read-only, timeout, size cap), `schema.py`
- `src/sql_copilot/security/validator.py` - `validate_sql()`, the security gate
- `src/sql_copilot/agent/` - `prompts.py`, `chain.py` (`SqlCopilot.ask()` -> `Answer`)
- `src/sql_copilot/api/` - FastAPI app (step 5)
- `tests/` - pytest; the LLM is always faked (`RecordingFake` in `tests/test_agent.py`)

## Rules
1. **Never put secrets in code or git.** `.env` is ignored; only `.env.example` is committed.
2. Tests must never call the real Anthropic API. Use the fake LLM.
3. Do not weaken `security/validator.py` or `db/connection.py` without a test that proves why.
   Policy is deny-by-default: SELECT only, table allowlist, `email` column blocked, LIMIT forced.
4. Any change must keep `pytest` and `ruff check .` green before committing.
5. Error details (DB errors, validator reasons) go to logs, never to API clients.
6. Small focused commits, imperative message, conventional prefix (feat/fix/docs/chore/test).
7. Work on your own branch/worktree; do not edit files outside your task's scope
   (in particular: do not edit `README.md` - the owner updates the roadmap when merging).

## Roadmap
- [x] 1 skeleton - [x] 2 sample DB - [x] 3 LangChain agent - [x] 4 validator (+ red-team hardening)
- [x] 5 FastAPI: `POST /ask`, `GET /health`, API-key auth, rate limit (slowapi), generic errors
- [x] 6 Claude skill `sql-guardrails` in `.claude/skills/`
- [ ] 7 CI: GitHub Actions (ruff + pytest, no secrets needed)
- [ ] 8 Docker + free-tier cloud deploy (DB is seeded at build time; it is not in git)
