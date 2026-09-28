"""
Background Tender Deadline & Reminder Scheduler.
Runs a background daemon thread periodically checking for due reminders,
emitting in-app notifications, managing expired statuses, and preventing duplicate alerts.
"""

import threading
import time
import logging
import os
import shutil
from datetime import datetime, timezone
from typing import Optional
from deadlines.database import (
    get_db_connection,
    DeadlineDB,
    TimezoneHelper,
    DEFAULT_TIMEZONE
)

logger = logging.getLogger("DeadlineScheduler")

class DeadlineScheduler:
    """
    Periodic background scheduler checking and firing due tender reminders.
    """

    _thread: Optional[threading.Thread] = None
    _running: bool = False
    _check_interval: int = 20  # Check every 20 seconds

    @classmethod
    def start(cls, check_interval: int = 20):
        """Starts the background scheduler daemon thread."""
        if cls._running:
            return

        cls._check_interval = check_interval
        cls._running = True
        cls._thread = threading.Thread(target=cls._run_loop, daemon=True, name="DeadlineSchedulerThread")
        cls._thread.start()
        print(f"[DeadlineScheduler] Background reminder scheduler started (interval: {cls._check_interval}s).")

    @classmethod
    def stop(cls):
        """Stops the background scheduler."""
        cls._running = False

    @classmethod
    def _run_loop(cls):
        """Main periodic loop."""
        # Initial run after 2 seconds
        time.sleep(2)
        while cls._running:
            try:
                cls.check_and_fire_reminders()
            except Exception as e:
                print(f"[DeadlineScheduler] Error during reminder check cycle: {e}")

            time.sleep(cls._check_interval)

    @classmethod
    def check_and_fire_reminders(cls) -> int:
        """
        Queries DB for due reminders and generates notifications.
        Returns the number of notifications generated in this cycle.
        """
        now_utc_str = TimezoneHelper.now_utc_iso()
        now_dt = TimezoneHelper.now_utc()
        fired_count = 0

        with get_db_connection() as conn:
            # 1. Query pending reminders where reminder_time_utc <= now_utc_str and sent = 0
            pending = conn.execute("""
                SELECT r.id AS reminder_id, r.tender_id, r.reminder_offset, r.reminder_label,
                       r.notification_type, r.reminder_time_utc,
                       t.title, t.organization, t.submission_deadline, t.submission_deadline_utc,
                       t.timezone
                FROM reminders r
                JOIN tenders t ON r.tender_id = t.id
                WHERE r.sent = 0 AND r.reminder_time_utc <= ?;
            """, (now_utc_str,)).fetchall()

            for row in pending:
                rem_id = row["reminder_id"]
                tender_id = row["tender_id"]
                title = row["title"]
                offset = row["reminder_offset"]
                tz_name = row["timezone"] or DEFAULT_TIMEZONE
                deadline_utc = row["submission_deadline_utc"]

                # Get local formatted deadline time
                display_info = TimezoneHelper.to_local_display(deadline_utc, tz_name)
                deadline_formatted = display_info.get("formatted", "Not specified")

                # Choose notification title and urgency style
                if "1h" in offset or "6h" in offset:
                    notif_title = f"🔴 Urgent: Tender deadline in {row['reminder_label']}"
                    notif_type = "urgent"
                elif "24h" in offset or "1d" in offset:
                    notif_title = f"🟠 Tender deadline tomorrow"
                    notif_type = "warning"
                elif "3d" in offset:
                    notif_title = f"🟡 Tender deadline in 3 days"
                    notif_type = "warning"
                else:
                    notif_title = f"🔵 Tender deadline approaching ({row['reminder_label']})"
                    notif_type = "info"

                notif_msg = f'"{title}" is due {row["reminder_label"]} at {display_info.get("time", "12:00 PM")} ({display_info.get("date", "")}).'

                # Atomic insert notification & mark reminder sent
                conn.execute("""
                    INSERT INTO notifications (id, tender_id, reminder_id, title, message, type, is_read, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?);
                """, (
                    f"notif_{rem_id}",
                    tender_id,
                    rem_id,
                    notif_title,
                    notif_msg,
                    notif_type,
                    now_utc_str
                ))

                conn.execute("""
                    UPDATE reminders SET sent = 1, sent_at = ? WHERE id = ?;
                """, (now_utc_str, rem_id))

                fired_count += 1
                try:
                    print(f"[DeadlineScheduler] Fired reminder for '{title}': {notif_title.encode('ascii', 'ignore').decode('ascii')}")
                except Exception:
                    pass

            # 2. Check for newly expired tenders — auto-delete all associated data
            expired_tenders = conn.execute("""
                SELECT id, title, submission_deadline_utc, timezone, status, file_name
                FROM tenders
                WHERE submission_deadline_utc <= ? AND status != 'DEADLINE_PASSED';
            """, (now_utc_str,)).fetchall()

            for t in expired_tenders:
                t_id = t["id"]
                t_title = t["title"]
                t_file_name = t["file_name"] or ""

                # Mark status expired first
                conn.execute("UPDATE tenders SET status = 'DEADLINE_PASSED', updated_at = ? WHERE id = ?;", (now_utc_str, t_id))

                # Emit expiry notification before wiping data
                exists = conn.execute("SELECT id FROM notifications WHERE tender_id = ? AND type = 'expired';", (t_id,)).fetchone()
                if not exists:
                    conn.execute("""
                        INSERT INTO notifications (id, tender_id, reminder_id, title, message, type, is_read, created_at)
                        VALUES (?, ?, NULL, ?, ?, 'expired', 0, ?);
                    """, (
                        f"notif_exp_{t_id}",
                        t_id,
                        "⚫ Submission Deadline Passed — Files Deleted",
                        f'The deadline for "{t_title}" has passed. All associated files and conversations have been automatically removed.',
                        now_utc_str
                    ))
                    fired_count += 1

                # ----------------------------------------------------------------
                # AUTO-CLEANUP: delete PDF file, RAG index, summaries, chat data
                # ----------------------------------------------------------------
                cls._cleanup_expired_tender_data(t_id, t_file_name)

                try:
                    print(f"[DeadlineScheduler] Auto-cleaned expired tender: '{t_title}' (id={t_id})")
                except Exception:
                    pass

        return fired_count

    @classmethod
    def _cleanup_expired_tender_data(cls, tender_id: str, file_name: str = ""):
        """
        Deletes ALL data associated with an expired tender:
        - PDF file from uploads/ folder
        - FAISS vector index from temp/vector_stores/
        - BM25 keyword cache from temp/bm25_indexes/
        - Document summary cache from temp/summaries/
        - Reminders and notifications for this tender from SQLite DB
        - In-memory RAG retriever (via app-level import if available)
        """
        import config

        # 1. Delete the uploaded PDF file
        upload_dir = config.UPLOAD_FOLDER
        temp_dir = config.TEMP_FOLDER

        # The tender_id matches the job_id which is the prefix of the saved PDF filename
        if upload_dir and os.path.isdir(upload_dir):
            for fname in os.listdir(upload_dir):
                if fname.startswith(tender_id):
                    pdf_path = os.path.join(upload_dir, fname)
                    try:
                        os.remove(pdf_path)
                        print(f"[DeadlineScheduler] Deleted PDF: {fname}")
                    except Exception as e:
                        print(f"[DeadlineScheduler] Failed to delete PDF {fname}: {e}")

        # 2. Delete vector store embeddings (Neon pgvector and local files)
        try:
            from rag.vector_store import VectorStore
            VectorStore(tender_id).delete()
        except Exception as e:
            print(f"[DeadlineScheduler] Failed to delete embeddings for {tender_id}: {e}")

        faiss_dir = os.path.join(temp_dir, "vector_stores")
        if os.path.isdir(faiss_dir):
            for ext in [".faiss", ".json", "_chunks.json"]:
                faiss_file = os.path.join(faiss_dir, f"{tender_id}{ext}")
                if os.path.exists(faiss_file):
                    try:
                        os.remove(faiss_file)
                    except Exception:
                        pass

        # 3. Delete BM25 keyword index cache
        bm25_dir = os.path.join(temp_dir, "bm25_indexes")
        if os.path.isdir(bm25_dir):
            for fname in os.listdir(bm25_dir):
                if fname.startswith(tender_id):
                    try:
                        os.remove(os.path.join(bm25_dir, fname))
                        print(f"[DeadlineScheduler] Deleted BM25 cache: {fname}")
                    except Exception as e:
                        print(f"[DeadlineScheduler] Failed to delete BM25 cache {fname}: {e}")

        # 4. Delete document summary cache
        summaries_dir = os.path.join(temp_dir, "summaries")
        summary_file = os.path.join(summaries_dir, f"{tender_id}.json")
        if os.path.exists(summary_file):
            try:
                os.remove(summary_file)
                print(f"[DeadlineScheduler] Deleted summary cache: {tender_id}.json")
            except Exception as e:
                print(f"[DeadlineScheduler] Failed to delete summary cache: {e}")

        # 5. Delete reminders and notifications from DB
        try:
            with get_db_connection() as conn:
                conn.execute("DELETE FROM reminders WHERE tender_id = ?;", (tender_id,))
        except Exception as e:
            print(f"[DeadlineScheduler] Failed to clean reminders for {tender_id}: {e}")

        # 6. Remove from DocumentManager registry (JSON registry)
        try:
            from documents.document_manager import DocumentManager
            DocumentManager.delete_document(tender_id)
        except Exception as e:
            print(f"[DeadlineScheduler] Failed to remove document from registry: {e}")

        # 7. Clear in-memory chat conversation
        try:
            from chat.conversation import ConversationMemory
            ConversationMemory.clear_session(tender_id)
        except Exception as e:
            print(f"[DeadlineScheduler] Failed to clear chat session: {e}")

        # 8. Remove from in-memory RAG index (imported at app level)
        try:
            import app as _app
            _app.RAG_INDEXES.pop(tender_id, None)
            _app.JOBS.pop(tender_id, None)
        except Exception:
            pass  # App context not available; will be cleaned on next access

