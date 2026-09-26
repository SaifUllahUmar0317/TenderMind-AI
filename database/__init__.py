"""
Database package for TenderMind AI.
Provides support for Neon PostgreSQL with seamless local SQLite fallback.
"""

from database.connection import get_connection, is_neon_enabled, test_connection
from database.migrate import run_migration

__all__ = ["get_connection", "is_neon_enabled", "test_connection", "run_migration"]
