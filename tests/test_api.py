import pytest
from fastapi.testclient import TestClient

from fakes import ExplodingFake, RecordingFake
from sql_copilot.agent.chain import SqlCopilot
from sql_copilot.api.main import create_app
from sql_copilot.config import Settings
from sql_copilot.db.seed import build_database

KEY = "good-key-1"
OTHER_KEY = "good-key-2"


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    return str(build_database(tmp_path_factory.mktemp("api") / "sales.db"))


def make_client(
    db_path, *responses, llm=None, rate_limit="100/minute", api_keys=f"{KEY},{OTHER_KEY}"
):
    llm = llm or RecordingFake(responses=list(responses))
    settings = Settings(api_keys=api_keys, rate_limit=rate_limit, database_path=db_path)
    return TestClient(create_app(settings, SqlCopilot(llm, db_path)))


def ask(client, question="How many customers?", key=KEY, **kwargs):
    headers = {"X-API-Key": key} if key is not None else {}
    return client.post("/ask", json={"question": question}, headers=headers, **kwargs)


# --- health ---------------------------------------------------------------------------------


def test_health_needs_no_auth_and_is_not_rate_limited(db_path):
    client = make_client(db_path, rate_limit="2/minute")
    assert all(client.get("/health").status_code == 200 for _ in range(10))


# --- authentication --------------------------------------------------------------------------


@pytest.mark.parametrize("key", [None, "", "wrong", KEY + "x", KEY[:-1]])
def test_missing_or_wrong_key_is_401(db_path, key):
    response = ask(make_client(db_path, "SELECT 1"), key=key)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key."}


def test_no_configured_keys_rejects_everything(db_path):
    client = make_client(db_path, "SELECT 1", api_keys="")
    assert ask(client, key=KEY).status_code == 401
    assert ask(client, key="").status_code == 401


def test_every_configured_key_works(db_path):
    for key in (KEY, OTHER_KEY):
        client = make_client(db_path, "SELECT COUNT(*) AS n FROM customers", "60 customers.")
        assert ask(client, key=key).status_code == 200


# --- happy path and refusals -------------------------------------------------------------------


def test_successful_question(db_path):
    client = make_client(db_path, "SELECT COUNT(*) AS n FROM customers", "There are 60 customers.")
    response = ask(client)
    assert response.status_code == 200
    assert response.json() == {
        "answer": "There are 60 customers.",
        "refused": False,
        "sql": "SELECT COUNT(*) AS n FROM customers LIMIT 100",
        "columns": ["n"],
        "rows": [[60]],
    }


@pytest.mark.parametrize("malicious_sql", [
    "DROP TABLE customers",
    "SELECT email FROM customers",
    "SELECT sql FROM sqlite_master",
])
def test_refusal_is_generic_and_leaks_nothing(db_path, malicious_sql):
    response = ask(make_client(db_path, malicious_sql, "unused"))
    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is True
    assert set(body) == {"answer", "refused"}  # no sql, rows or columns
    text = response.text.lower()
    for leaked in ("drop table", "email", "sqlite_master", "customers", "not allowed"):
        assert leaked not in text


def test_database_error_details_are_not_exposed(db_path):
    response = ask(make_client(db_path, "SELECT nonexistent_col FROM products", "unused"))
    assert response.json()["refused"] is True
    assert "nonexistent_col" not in response.text
    assert "no such column" not in response.text


def test_upstream_llm_failure_is_503_without_details(db_path):
    response = ask(make_client(db_path, llm=ExplodingFake(responses=["x"])))
    assert response.status_code == 503
    assert response.json() == {"detail": "The service is temporarily unavailable."}
    assert "secret-internal-detail" not in response.text


def test_app_without_llm_key_starts_and_fails_closed(db_path):
    settings = Settings(api_keys=KEY, anthropic_api_key="", database_path=db_path)
    client = TestClient(create_app(settings))
    assert client.get("/health").status_code == 200
    response = ask(client)
    assert response.status_code == 503
    assert "ANTHROPIC" not in response.text


# --- input validation --------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [
    {},
    {"question": ""},
    {"question": "x" * 501},
    {"question": 123},
    {"question": "ok", "extra": "field"},
])
def test_invalid_payloads_are_422(db_path, payload):
    client = make_client(db_path, "SELECT 1")
    response = client.post("/ask", json=payload, headers={"X-API-Key": KEY})
    assert response.status_code == 422


def test_oversized_body_is_413(db_path):
    client = make_client(db_path, "SELECT 1")
    response = client.post(
        "/ask",
        content=b'{"question": "' + b"a" * 5000 + b'"}',
        headers={"X-API-Key": KEY, "Content-Type": "application/json"},
    )
    assert response.status_code == 413


# --- rate limiting -----------------------------------------------------------------------------


def test_rate_limit_returns_429_after_the_quota(db_path):
    client = make_client(db_path, *["SELECT COUNT(*) FROM orders", "ok"] * 5, rate_limit="3/minute")
    assert [ask(client).status_code for _ in range(3)] == [200, 200, 200]
    blocked = ask(client)
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Rate limit exceeded. Try again later."}
    assert blocked.headers["retry-after"] == "60"


def test_each_valid_key_has_its_own_quota(db_path):
    client = make_client(db_path, *["SELECT COUNT(*) FROM orders", "ok"] * 5, rate_limit="2/minute")
    for _ in range(2):
        assert ask(client, key=KEY).status_code == 200
    assert ask(client, key=KEY).status_code == 429
    assert ask(client, key=OTHER_KEY).status_code == 200


def test_rotating_fake_keys_does_not_evade_the_limit(db_path):
    # Brute-force attempt: a new bogus key on every request must still hit the limit.
    client = make_client(db_path, "SELECT 1", rate_limit="3/minute")
    statuses = [ask(client, key=f"guess-{i}").status_code for i in range(6)]
    assert statuses == [401, 401, 401, 429, 429, 429]
