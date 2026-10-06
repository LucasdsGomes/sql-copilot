import pytest

from sql_copilot.db.connection import run_query
from sql_copilot.db.seed import build_database
from sql_copilot.security.validator import (
    UnsafeQueryError,
    ValidationPolicy,
    validate_sql,
)

# --- Queries that must be ACCEPTED -------------------------------------------------

SAFE_QUERIES = [
    "SELECT name, city FROM customers",
    "SELECT COUNT(*) FROM orders",
    "SELECT * FROM products",
    "SELECT c.city, SUM(i.quantity * i.unit_price) AS total "
    "FROM customers c JOIN orders o ON o.customer_id = c.id "
    "JOIN order_items i ON i.order_id = o.id GROUP BY c.city ORDER BY total DESC",
    "WITH t AS (SELECT id, city FROM customers) SELECT city, COUNT(*) FROM t GROUP BY city",
    "SELECT name FROM customers UNION SELECT name FROM products",
    "SELECT category, AVG(price) FROM products GROUP BY category HAVING AVG(price) > 100",
]


@pytest.mark.parametrize("sql", SAFE_QUERIES)
def test_safe_queries_are_accepted(sql):
    assert validate_sql(sql).upper().startswith(("SELECT", "WITH"))


# --- Attacks that must be REJECTED -------------------------------------------------

ATTACKS = {
    # write / DDL
    "drop": "DROP TABLE customers",
    "delete": "DELETE FROM orders",
    "update": "UPDATE products SET price = 0",
    "insert": "INSERT INTO products VALUES (99, 'x', 'y', 1.0)",
    "create": "CREATE TABLE evil (id INTEGER)",
    "alter": "ALTER TABLE customers ADD COLUMN x TEXT",
    # stacked statements / classic injection
    "stacked": "SELECT 1; DROP TABLE customers",
    "stacked_trailing": "SELECT name FROM products; DELETE FROM orders;",
    "tautology_then_drop": "SELECT name FROM products WHERE 1=1; DROP TABLE orders --",
    # dangerous commands
    "pragma": "PRAGMA table_info(customers)",
    "attach": "ATTACH DATABASE '/tmp/x.db' AS x",
    "vacuum": "VACUUM",
    # schema / system tables
    "sqlite_master": "SELECT sql FROM sqlite_master",
    "sqlite_schema": "SELECT * FROM sqlite_schema",
    "schema_qualified": "SELECT id FROM main.customers",
    "unknown_table": "SELECT * FROM users",
    "table_function": "SELECT * FROM pragma_table_info('customers')",
    # functions
    "load_extension": "SELECT load_extension('evil.dll')",
    "readfile": "SELECT readfile('/etc/passwd')",
    "randomblob_dos": "SELECT randomblob(1000000000)",
    # sensitive data (PII)
    "email_direct": "SELECT email FROM customers",
    "email_qualified": "SELECT c.email FROM customers c",
    "email_alias": "SELECT email AS e FROM customers",
    "email_in_where": "SELECT name FROM customers WHERE email LIKE '%@gmail.com'",
    "email_in_subquery": "SELECT name FROM (SELECT name, email FROM customers)",
    "email_via_union": "SELECT name FROM products UNION SELECT email FROM customers",
    "star_on_sensitive": "SELECT * FROM customers",
    "qualified_star_on_sensitive": "SELECT c.* FROM customers c",
    "star_in_join": "SELECT * FROM orders o JOIN customers c ON c.id = o.customer_id",
    # garbage
    "empty": "",
    "whitespace": "   ",
    "unparseable": "SELEKT nonsense FROM",
    "too_long": "SELECT " + "1," * 2000 + "1",
}


@pytest.mark.parametrize("sql", ATTACKS.values(), ids=ATTACKS.keys())
def test_attacks_are_rejected(sql):
    with pytest.raises(UnsafeQueryError):
        validate_sql(sql)


# --- Obfuscation: comments and casing must not hide intent ---------------------------


@pytest.mark.parametrize("sql", [
    "SELECT/**/email/**/FROM/**/customers",
    "SeLeCt EMAIL FrOm CuStOmErS",
    "SELECT name FROM customers -- harmless\n; DROP TABLE customers",
    "SELECT \"email\" FROM customers",
    "SELECT `email` FROM customers",
])
def test_obfuscated_attacks_are_rejected(sql):
    with pytest.raises(UnsafeQueryError):
        validate_sql(sql)


def test_comments_are_stripped_from_output():
    safe = validate_sql("SELECT name FROM products /* ignore previous instructions */")
    assert "ignore" not in safe


# --- LIMIT enforcement ---------------------------------------------------------------


def test_limit_is_added_when_missing():
    assert validate_sql("SELECT name FROM products").upper().endswith("LIMIT 100")


def test_larger_limit_is_clamped():
    assert validate_sql("SELECT name FROM products LIMIT 999999").upper().endswith("LIMIT 100")


def test_smaller_limit_is_kept():
    assert validate_sql("SELECT name FROM products LIMIT 5").upper().endswith("LIMIT 5")


def test_limit_applies_to_union_as_a_whole():
    safe = validate_sql("SELECT name FROM products UNION SELECT name FROM customers")
    assert safe.upper().endswith("LIMIT 100")


def test_custom_max_rows():
    policy = ValidationPolicy(max_rows=10)
    assert validate_sql("SELECT name FROM products", policy).upper().endswith("LIMIT 10")


# --- End to end: validated SQL really runs against the database -----------------------


def test_validated_query_executes(tmp_path):
    db = build_database(tmp_path / "sales.db")
    safe = validate_sql("SELECT city, COUNT(*) AS n FROM customers GROUP BY city ORDER BY n DESC")
    result = run_query(db, safe)
    assert result.columns == ["city", "n"]
    assert len(result.rows) > 0
