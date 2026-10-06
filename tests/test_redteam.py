"""Red-team findings for validate_sql().

106 probes were run by an independent reviewer (Antigravity) against the validator. Each reported
finding was re-verified against the real database before acting on it:

* Section 1: confirmed weaknesses, now fixed (regression tests).
* Section 2: reported findings that are NOT vulnerabilities; the behaviour is intentional and the
  reason is recorded here so nobody "fixes" it later by mistake.
* Section 3: a sample of attacks that were already blocked.
"""

import pytest

from sql_copilot.db.connection import run_query
from sql_copilot.db.seed import build_database
from sql_copilot.security.validator import UnsafeQueryError, validate_sql


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    return build_database(tmp_path_factory.mktemp("redteam") / "sales.db")


# --- Section 1: confirmed and fixed ------------------------------------------------------

FIXED = {
    # Unbounded recursion can pin the CPU (the outer LIMIT does not stop aggregates).
    "recursive_cte": "WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM c) "
                     "SELECT COUNT(*) FROM c",
    "recursive_cte_bounded": "WITH RECURSIVE cnt(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM cnt "
                             "WHERE n < 10) SELECT n FROM cnt",
    # CTE named like a system/real table made table checks ambiguous. SQLite itself refused
    # these, but the validator should not rely on that.
    "cte_shadows_sqlite_master": "WITH sqlite_master AS (SELECT * FROM sqlite_master) "
                                 "SELECT * FROM sqlite_master",
    "cte_forward_reference": "WITH a AS (SELECT * FROM sqlite_master), sqlite_master AS "
                             "(SELECT 1) SELECT * FROM a",
    "cte_shadows_allowed_table": "WITH products AS (SELECT 1 AS id) SELECT id FROM products",
    # VALUES has no legitimate use here and can inject literal rows into results.
    "values_with_email_alias": "SELECT * FROM (VALUES (1,'x')) t(id, email)",
    "values_cte": "WITH t(a, b) AS (VALUES (1, 'x')) SELECT * FROM t",
    "values_union_injection": "SELECT name FROM products UNION ALL "
                              "SELECT * FROM (VALUES ('injected')) t(name)",
    # Environment introspection (leaks SQLite build, connection state).
    "sqlite_version": "SELECT sqlite_version()",
    "sqlite_source_id": "SELECT sqlite_source_id()",
    "changes": "SELECT changes()",
    "total_changes": "SELECT total_changes()",
    "last_insert_rowid": "SELECT last_insert_rowid()",
}


@pytest.mark.parametrize("sql", FIXED.values(), ids=FIXED.keys())
def test_confirmed_weaknesses_are_rejected(sql):
    with pytest.raises(UnsafeQueryError):
        validate_sql(sql)


# --- Section 2: reported, but intentionally allowed ---------------------------------------


def test_limit_expression_is_normalised_not_executed(db_path):
    # LIMIT 1+1 / LIMIT (SELECT 1000): the validator replaces the whole LIMIT node, so the
    # subquery never reaches the database. No leak channel, hence no need to reject.
    queries = [
        "SELECT name FROM products LIMIT 1+1",
        "SELECT name FROM products LIMIT (SELECT 1000)",
    ]
    for sql in queries:
        safe = validate_sql(sql)
        assert safe.upper().endswith("LIMIT 100")
        assert "1000" not in safe
        assert len(run_query(db_path, safe).rows) == 12


def test_stray_semicolons_are_harmless():
    # Only one real statement exists, and the output is regenerated without any semicolon.
    safe = validate_sql(";SELECT name FROM products;")
    assert ";" not in safe


def test_limit_zero_is_allowed():
    # Returns nothing. Error details are not shown to users, so it is no schema-probing oracle.
    assert validate_sql("SELECT name FROM products LIMIT 0").upper().endswith("LIMIT 0")


def test_offset_is_allowed_but_limit_still_enforced():
    # Paging through data the caller may already read; bounded by LIMIT, auth and rate limit.
    safe = validate_sql("SELECT name FROM products OFFSET 50")
    assert "LIMIT 100" in safe.upper()


def test_date_now_is_allowed():
    # Needed for legitimate questions such as "orders from the last 30 days".
    assert "NOW" in validate_sql("SELECT date('now')").upper()


def test_alias_named_email_is_allowed_when_no_email_data_is_read():
    # Aliases hold no data. Reading an actual `email` column is still blocked (Section 3).
    validate_sql("SELECT name FROM (SELECT name FROM customers) AS email")


def test_star_on_non_sensitive_subquery_is_allowed():
    validate_sql("SELECT * FROM (SELECT name FROM products) AS p")


# --- Section 3: already blocked --------------------------------------------------------------

BLOCKED = [
    "SELECT email FROM customers",
    "WITH t AS (SELECT name, email AS addr FROM customers) SELECT addr FROM t",
    "SELECT name FROM customers ORDER BY email",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM customers",
    "WITH meta AS (SELECT sql FROM sqlite_master) SELECT sql FROM meta",
    "SELECT 1; DROP TABLE customers",
    "SELECT load_extension('evil.dll')",
    "SELECT * FROM pragma_table_info('customers')",
    "SELECT name FROM customers WHERE EXISTS "
    "(SELECT 1 FROM customers c2 WHERE c2.email = customers.name)",
]


@pytest.mark.parametrize("sql", BLOCKED)
def test_already_blocked(sql):
    with pytest.raises(UnsafeQueryError):
        validate_sql(sql)
