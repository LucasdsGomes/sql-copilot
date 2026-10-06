# SQL Copilot

Natural-language questions in, safe SQL out. An AI agent (LangChain + Claude) that turns questions
into SQL, validates every query against security guardrails, and serves answers through a
rate-limited, authenticated API.

> Work in progress - built step by step.

## Planned architecture

```
User -> FastAPI (API key + rate limit)
     -> LangChain agent (question -> SQL)
     -> sqlglot validator (SELECT only, forced LIMIT, table allowlist)
     -> read-only SQLite
     -> LLM summarises result -> answer
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
cp .env.example .env          # then add your ANTHROPIC_API_KEY
pytest
```

## Roadmap

- [x] Project skeleton
- [x] Sample database (SQLite, read-only access)
- [x] LangChain SQL agent (3-step chain, tested with a fake LLM)
- [x] Security validator (sqlglot) + DB limits (timeout, value size), red-teamed by a second agent
- [x] FastAPI + auth + rate limit
- [x] Claude skill `sql-guardrails`
- [x] Tests + CI (GitHub Actions)
- [ ] Docker + free-tier cloud deploy

## Run the API

```bash
.venv\Scripts\python scripts/seed_db.py
.venv\Scripts\python -m uvicorn sql_copilot.api.main:app --port 8000
```

```bash
curl -X POST localhost:8000/ask -H "X-API-Key: <one of API_KEYS>" -H "Content-Type: application/json" -d "{\"question\": \"Top 3 cities by revenue?\"}"
```

- `GET /health` - no auth, not rate limited.
- `POST /ask` - requires `X-API-Key`; limited by `RATE_LIMIT`: each valid key has its own quota, and all requests without a valid key share one.
- Clients only get generic errors (`401`, `422`, `429`, `503`); details stay in the server log.
- Interactive docs at `/docs`.
