"""Builds the sample sales database with deterministic fake data."""

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    city TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price REAL NOT NULL
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    order_date TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL
);
"""

FIRST_NAMES = ["Ana", "Bruno", "Carla", "Diego", "Eduarda", "Felipe", "Gabriela", "Hugo",
               "Isabela", "João", "Karina", "Lucas", "Marina", "Nicolas", "Olivia", "Pedro"]
LAST_NAMES = ["Silva", "Souza", "Oliveira", "Santos", "Lima", "Pereira", "Costa", "Almeida",
              "Ribeiro", "Carvalho", "Gomes", "Martins"]
CITIES = ["São Paulo", "Rio de Janeiro", "Belo Horizonte", "Curitiba", "Porto Alegre",
          "Salvador", "Recife", "Brasília"]
PRODUCTS = [
    ("Notebook 14", "Eletrônicos", 3499.90), ("Mouse sem fio", "Eletrônicos", 89.90),
    ("Teclado mecânico", "Eletrônicos", 349.00), ("Monitor 24", "Eletrônicos", 899.00),
    ("Cadeira ergonômica", "Móveis", 1299.00), ("Mesa de escritório", "Móveis", 749.00),
    ("Luminária LED", "Móveis", 129.90), ("Caderno universitário", "Papelaria", 24.90),
    ("Caneta gel (kit)", "Papelaria", 19.90), ("Agenda 2026", "Papelaria", 49.90),
    ("Mochila executiva", "Acessórios", 219.00), ("Garrafa térmica", "Acessórios", 79.90),
]
STATUSES = ["paid", "paid", "paid", "shipped", "delivered", "delivered", "cancelled"]


def build_database(path: str | Path, seed: int = 42, n_customers: int = 60,
                   n_orders: int = 300) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    rng = random.Random(seed)
    today = date(2026, 6, 30)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)

        customers = []
        for i in range(1, n_customers + 1):
            first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            created = today - timedelta(days=rng.randint(200, 900))
            customers.append((i, f"{first} {last}", f"{first}.{last}{i}@example.com".lower(),
                              rng.choice(CITIES), created.isoformat()))
        conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?)", customers)

        conn.executemany(
            "INSERT INTO products VALUES (?,?,?,?)",
            [(i, n, c, p) for i, (n, c, p) in enumerate(PRODUCTS, start=1)],
        )

        item_id = 1
        for order_id in range(1, n_orders + 1):
            order_date = today - timedelta(days=rng.randint(0, 365))
            conn.execute(
                "INSERT INTO orders VALUES (?,?,?,?)",
                (order_id, rng.randint(1, n_customers), order_date.isoformat(),
                 rng.choice(STATUSES)),
            )
            for product_id in rng.sample(range(1, len(PRODUCTS) + 1), rng.randint(1, 4)):
                price = PRODUCTS[product_id - 1][2]
                conn.execute(
                    "INSERT INTO order_items VALUES (?,?,?,?,?)",
                    (item_id, order_id, product_id, rng.randint(1, 3), price),
                )
                item_id += 1
        conn.commit()
    finally:
        conn.close()
    return path
