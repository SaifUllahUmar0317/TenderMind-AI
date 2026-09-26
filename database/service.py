"""
Database Service Layer for TenderMind AI.
Reads and writes to Neon PostgreSQL when enabled, with transparent SQLite/JSON fallback.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from database.connection import is_neon_enabled, get_connection

logger = logging.getLogger("tendermind.db.service")

class NeonDatabaseService:
    """Handles high-level data operations on Neon PostgreSQL."""

    @classmethod
    def save_document(cls, doc_id: str, filename: str, page_count: int, file_size: int, overall_type: str = "digital", status: str = "ready") -> bool:
        if not is_neon_enabled():
            return False
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO documents (id, filename, page_count, file_size, overall_type, status, is_active, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET
                        filename = EXCLUDED.filename,
                        page_count = EXCLUDED.page_count,
                        file_size = EXCLUDED.file_size,
                        status = EXCLUDED.status,
                        is_active = TRUE,
                        updated_at = CURRENT_TIMESTAMP;
                """, (doc_id, filename, page_count, file_size, overall_type, status))
                # Set others inactive
                cur.execute("UPDATE documents SET is_active = FALSE WHERE id != %s;", (doc_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to save document to Neon: {e}")
            return False

    @classmethod
    def list_documents(cls) -> List[Dict[str, Any]]:
        if not is_neon_enabled():
            return []
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT id as document_id, filename, page_count, file_size, overall_type, status, is_active, created_at FROM documents ORDER BY created_at DESC;")
                rows = cur.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Failed to list documents from Neon: {e}")
            return []

    @classmethod
    def set_active_document(cls, doc_id: str) -> bool:
        if not is_neon_enabled():
            return False
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("UPDATE documents SET is_active = (id = %s);", (doc_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to set active document in Neon: {e}")
            return False

    @classmethod
    def save_chat_message(cls, session_id: str, role: str, content: str, document_id: Optional[str] = None, citations: Optional[list] = None, question_type: Optional[str] = None, provider: str = "groq") -> bool:
        if not is_neon_enabled():
            return False
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO chat_conversations (session_id, document_id, role, content, citations, question_type, provider)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                """, (session_id, document_id, role, content, json.dumps(citations or []), question_type, provider))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to save chat to Neon: {e}")
            return False

    @classmethod
    def get_chat_history(cls, session_id: str) -> List[Dict[str, Any]]:
        if not is_neon_enabled():
            return []
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT role, content, citations, question_type, provider, created_at 
                    FROM chat_conversations 
                    WHERE session_id = %s 
                    ORDER BY created_at ASC;
                """, (session_id,))
                rows = cur.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Failed to fetch chat history from Neon: {e}")
            return []

    @classmethod
    def save_summary_and_equipment(cls, doc_id: str, summary_data: dict, equipment_items: list = None) -> bool:
        if not is_neon_enabled():
            return False
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                # Save summary
                cur.execute("""
                    INSERT INTO document_summaries (document_id, tender_title, organization, executive_summary, hierarchical_summary, section_summaries, metadata_kv, deadline_info)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """, (
                    doc_id,
                    summary_data.get("title") or summary_data.get("tender_title"),
                    summary_data.get("organization"),
                    summary_data.get("executive_summary"),
                    json.dumps(summary_data),
                    json.dumps(summary_data.get("section_summaries", [])),
                    json.dumps(summary_data.get("metadata_kv", [])),
                    json.dumps(summary_data.get("deadline_info", {}))
                ))

                # Save equipment items
                items = equipment_items or summary_data.get("structured_equipment", [])
                for idx, item in enumerate(items):
                    cur.execute("""
                        INSERT INTO equipment_items (document_id, item_number, name, category, quantity, unit, specifications, source_page, raw_data)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """, (
                        doc_id,
                        str(idx + 1),
                        item.get("name", "Unknown Item"),
                        item.get("category", "Main Equipment"),
                        item.get("quantity", ""),
                        item.get("unit", ""),
                        json.dumps(item.get("specifications", [])),
                        item.get("source_page", 1),
                        json.dumps(item)
                    ))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to save summary and equipment to Neon: {e}")
            return False
