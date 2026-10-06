"""Create the sample database: python scripts/seed_db.py"""

from sql_copilot.config import get_settings
from sql_copilot.db.seed import build_database

if __name__ == "__main__":
    path = build_database(get_settings().database_path)
    print(f"Database created at {path}")
