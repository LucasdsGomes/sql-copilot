import sqlite3

import pytest

from sql_copilot.db.connection import run_query
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
