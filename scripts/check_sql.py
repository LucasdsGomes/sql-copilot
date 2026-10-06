"""Check a query against the security policy: python scripts/check_sql.py "SELECT ..." """

import sys

from sql_copilot.security.validator import UnsafeQueryError, validate_sql

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('Usage: python scripts/check_sql.py "SELECT ..."')
    try:
        print("SAFE:", validate_sql(" ".join(sys.argv[1:])))
    except UnsafeQueryError as e:
        print("REJECTED:", e)
        sys.exit(1)
