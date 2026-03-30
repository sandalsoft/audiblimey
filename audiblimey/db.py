"""Database connection utilities for audiblimey."""

import psycopg2
from contextlib import contextmanager

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "audiblimey",
    "user": "audiblimey",
    "password": "audiblimey_dev",
}


def get_connection():
    """Get a database connection."""
    return psycopg2.connect(**DB_CONFIG)


@contextmanager
def get_cursor(autocommit=False):
    """Context manager for database cursor."""
    conn = get_connection()
    conn.autocommit = autocommit
    try:
        cur = conn.cursor()
        yield cur
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
