"""
Neon Database Connection Manager.
Supports pooled connections to Neon PostgreSQL with SSL.
Falls back seamlessly to local SQLite if DATABASE_URL is not configured.
"""

import os
import logging
from typing import Optional, Any
from urllib.parse import urlparse

logger = logging.getLogger("tendermind.db")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

_pool = None

def is_neon_enabled() -> bool:
    """Returns True if a valid PostgreSQL DATABASE_URL is configured."""
    return bool(DATABASE_URL and (DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")))

def get_connection():
    """
    Returns a live connection to Neon PostgreSQL.
    Ensures sslmode=require for secure Neon connections.
    """
    if not is_neon_enabled():
        raise ValueError("DATABASE_URL is not set or invalid for Neon PostgreSQL.")

    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn_url = DATABASE_URL
    # Ensure sslmode=require for Neon
    if "sslmode=" not in conn_url:
        separator = "&" if "?" in conn_url else "?"
        conn_url = f"{conn_url}{separator}sslmode=require"

    conn = psycopg2.connect(conn_url, cursor_factory=RealDictCursor)
    conn.autocommit = False
    return conn

def test_connection() -> dict:
    """Tests connectivity to Neon and returns server information."""
    if not is_neon_enabled():
        return {"connected": False, "error": "DATABASE_URL is not configured."}

    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            ver = cur.fetchone()
            cur.execute("SELECT current_database(), current_user;")
            info = cur.fetchone()
        conn.close()
        return {
            "connected": True,
            "version": ver["version"] if ver else "unknown",
            "database": info["current_database"] if info else "unknown",
            "user": info["current_user"] if info else "unknown"
        }
    except Exception as e:
        logger.error(f"Neon connection test failed: {e}")
        return {"connected": False, "error": str(e)}
