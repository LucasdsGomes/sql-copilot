import sqlite3

import pytest

from sql_copilot.db.connection import QueryTimeoutError, run_query
from sql_copilot.db.seed import build_database


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    return build_database(tmp_path_factory.mktemp("db") / "sales.db")


def test_seed_creates_expected_tables(db_path):
    result = run_query(db_path, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    assert [r[0] for r in result.rows] == ["customers", "order_items", "orders", "products"]


def test_seed_is_deterministic(tmp_path):
    a = build_database(tmp_path / "a.db")
    b = build_database(tmp_path / "b.db")
    q = "SELECT SUM(quantity * unit_price) FROM order_items"
    assert run_query(a, q).rows == run_query(b, q).rows


def test_max_rows_truncates(db_path):
    result = run_query(db_path, "SELECT * FROM customers", max_rows=5)
    assert len(result.rows) == 5
    assert result.truncated is True


def test_not_truncated_when_under_limit(db_path):
    result = run_query(db_path, "SELECT * FROM products", max_rows=100)
    assert result.truncated is False


@pytest.mark.parametrize("sql", [
    "DROP TABLE customers",
    "DELETE FROM orders",
    "UPDATE products SET price = 0",
    "INSERT INTO products VALUES (99, 'x', 'y', 1.0)",
])
def test_writes_are_rejected_by_the_database(db_path, sql):
    with pytest.raises(sqlite3.OperationalError):
        run_query(db_path, sql)


def test_missing_database_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="seed_db.py"):
        run_query(tmp_path / "nope.db", "SELECT 1")


def test_runaway_recursive_query_is_aborted(db_path):
    # Bypasses the validator on purpose: the database layer must protect itself too.
    sql = "WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM c) SELECT COUNT(*) FROM c"
    with pytest.raises(QueryTimeoutError):
        run_query(db_path, sql, timeout_s=0.5)


def test_cartesian_product_is_aborted(db_path):
    sql = "SELECT COUNT(*) FROM order_items a, order_items b, order_items c, order_items d"
    with pytest.raises(QueryTimeoutError):
        run_query(db_path, sql, timeout_s=0.5)


def test_oversized_strings_are_rejected_by_the_database(db_path):
    # Building a string past the length cap fails instead of exhausting memory.
    sql = "SELECT replace(printf('%100000d', 1), ' ', printf('%100000d', 2))"
    with pytest.raises(sqlite3.Error, match="too big"):
        run_query(db_path, sql)


def test_absurd_printf_width_yields_null_not_a_huge_string(db_path):
    result = run_query(db_path, "SELECT printf('%1000000000d', 1)")
    assert result.rows == [(None,)]
