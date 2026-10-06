"""FastAPI app: authenticated, rate-limited access to the SQL copilot.

Security notes
  * Fail closed: with no API_KEYS configured, every /ask request is rejected.
  * Rate limiting runs as middleware, i.e. BEFORE authentication, so wrong keys are limited too.
    The bucket is the API key only when it is valid; every other request shares ONE global bucket.
    Not keyed by IP on purpose: behind cloud proxies the peer IP varies per request (measured on
    Render: ~3 proxy IPs, so an IP bucket multiplied the quota), and trusting X-Forwarded-For
    would let a client forge its identity. Requests without a valid key can do nothing useful
    anyway, so sharing their quota costs legitimate users nothing.
  * Clients only ever see generic error messages; the real reason goes to the server log.
"""

import hmac
import logging
import threading
from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from sql_copilot.agent.chain import SqlCopilot, build_llm
from sql_copilot.config import Settings, get_settings

logger = logging.getLogger("sql_copilot.api")

MAX_BODY_BYTES = 4096
API_KEY_HEADER = "X-API-Key"
ANONYMOUS_BUCKET = "anonymous"


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=500)


class AskResponse(BaseModel):
    answer: str
    refused: bool = False
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[list[Any]] | None = None


class _LazyCopilot:
    """Builds the agent on first use, so the app starts (and /health works) without an LLM key."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._copilot: SqlCopilot | None = None
        self._lock = threading.Lock()

    def get(self) -> SqlCopilot:
        with self._lock:
            if self._copilot is None:
                self._copilot = SqlCopilot(
                    build_llm(self._settings), self._settings.database_path
                )
            return self._copilot


def _is_valid_key(candidate: str | None, valid_keys: set[str]) -> bool:
    if not candidate:
        return False
    matched = False
    for key in valid_keys:  # no early exit: timing must not reveal which key matched
        matched |= hmac.compare_digest(candidate.encode(), key.encode())
    return matched


def create_app(settings: Settings | None = None, copilot: SqlCopilot | None = None) -> FastAPI:
    settings = settings or get_settings()
    valid_keys = settings.api_key_set
    if not valid_keys:
        logger.warning("API_KEYS is empty: every /ask request will be rejected.")
    get_copilot: Callable[[], SqlCopilot] = (
        (lambda: copilot) if copilot is not None else _LazyCopilot(settings).get
    )

    def rate_limit_key(request: Request) -> str:
        header = request.headers.get(API_KEY_HEADER)
        if _is_valid_key(header, valid_keys):
            return f"key:{header}"
        return ANONYMOUS_BUCKET

    limiter = Limiter(key_func=rate_limit_key, default_limits=[settings.rate_limit])
    app = FastAPI(title="SQL Copilot", version="0.1.0")
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_BODY_BYTES:
            return JSONResponse({"detail": "Request too large."}, status_code=413)
        return await call_next(request)

    # Must be a plain `def`: SlowAPIMiddleware silently falls back to its own (config-revealing)
    # handler when given a coroutine function.
    @app.exception_handler(RateLimitExceeded)
    def rate_limited(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            {"detail": "Rate limit exceeded. Try again later."},
            status_code=429,
            headers={"Retry-After": "60"},
        )

    api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)

    def require_api_key(key: str | None = Depends(api_key_header)) -> str:
        if not _is_valid_key(key, valid_keys):
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing API key.",
                headers={"WWW-Authenticate": "ApiKey"},
            )
        return key  # type: ignore[return-value]

    @app.get("/health")
    @limiter.exempt
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/ask", response_model=AskResponse, response_model_exclude_none=True)
    def ask(body: AskRequest, _key: str = Depends(require_api_key)) -> AskResponse:
        try:
            result = get_copilot().ask(body.question)
        except Exception:
            logger.exception("Unexpected failure while answering a question")
            raise HTTPException(
                status_code=503, detail="The service is temporarily unavailable."
            ) from None

        if result.refused:
            logger.warning("Question refused: %s | sql=%r", result.refused_reason, result.sql)
            return AskResponse(answer=result.answer, refused=True)
        return AskResponse(
            answer=result.answer,
            sql=result.sql,
            columns=result.columns,
            rows=[list(r) for r in result.rows or []],
        )

    return app


app = create_app()
