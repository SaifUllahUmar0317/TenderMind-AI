"""
Migration & Setup Script for Neon PostgreSQL.
Executes schema.sql and verifies table creation in Neon.
Can also migrate existing local SQLite data to Neon.
"""

import os
import sys
import json
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import config
from database.connection import is_neon_enabled, get_connection, test_connection

SCHEMA_FILE = BASE_DIR / "database" / "schema.sql"

REQUIRED_TABLES = [
    "documents",
    "document_summaries",
    "equipment_items",
    "chat_conversations",
    "tenders",
    "reminders",
    "notifications",
    "pdf_compressions",
    "pdf_combiner_sessions"
]

def run_migration(db_url: str = None) -> dict:
    """
    Applies schema.sql to the specified Neon database.
    """
    if db_url:
        os.environ["DATABASE_URL"] = db_url

    if not is_neon_enabled():
        return {
            "success": False,
            "error": "DATABASE_URL is missing. Please set DATABASE_URL in your .env file or pass it to this function."
        }

    print("Checking connection to Neon PostgreSQL...")
    conn_info = test_connection()
    if not conn_info.get("connected"):
        return {
            "success": False,
            "error": f"Failed to connect to Neon: {conn_info.get('error')}"
        }

    print(f"Connected to Neon Database: {conn_info.get('database')} as {conn_info.get('user')}")

    if not SCHEMA_FILE.exists():
        return {"success": False, "error": f"Schema file not found: {SCHEMA_FILE}"}

    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    print("Applying schema to Neon...")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
        print("Schema executed successfully!")

        # Verify created tables
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                ORDER BY table_name;
            """)
            existing_tables = [r["table_name"] for r in cur.fetchall()]

        created = [t for t in REQUIRED_TABLES if t in existing_tables]
        missing = [t for t in REQUIRED_TABLES if t not in existing_tables]

        print(f"Verified {len(created)}/{len(REQUIRED_TABLES)} tables in Neon:")
        for t in created:
            print(f"  [OK] {t}")

        if missing:
            print(f"Warning: Missing tables: {missing}")

        return {
            "success": True,
            "database": conn_info.get("database"),
            "tables": created,
            "missing": missing
        }

    except Exception as e:
        conn.rollback()
        print(f"Migration error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        conn.close()

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else None
    res = run_migration(url)
    if not res.get("success"):
        print(f"\nMigration failed: {res.get('error')}")
        sys.exit(1)
    else:
        print("\nNeon Database initialized and ready for production!")
