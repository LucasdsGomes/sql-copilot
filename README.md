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
- [ ] Sample database (SQLite)
- [ ] LangChain SQL agent
- [ ] Security validator
- [ ] FastAPI + auth + rate limit
- [ ] Claude skill `sql-guardrails`
- [ ] Tests + CI (GitHub Actions)
- [ ] Docker + free-tier cloud deploy
