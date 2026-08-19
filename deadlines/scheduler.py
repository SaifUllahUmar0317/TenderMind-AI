"""
Background Tender Deadline & Reminder Scheduler.
Runs a background daemon thread periodically checking for due reminders,
emitting in-app notifications, managing expired statuses, and preventing duplicate alerts.
"""

import threading
import time
import logging
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

            # 2. Check for newly expired tenders that need status update and expiry notification
            expired_tenders = conn.execute("""
                SELECT id, title, submission_deadline_utc, timezone, status
                FROM tenders
                WHERE submission_deadline_utc <= ? AND status != 'DEADLINE_PASSED';
            """, (now_utc_str,)).fetchall()

            for t in expired_tenders:
                t_id = t["id"]
                t_title = t["title"]
                conn.execute("UPDATE tenders SET status = 'DEADLINE_PASSED', updated_at = ? WHERE id = ?;", (now_utc_str, t_id))

                # Check if expiry notification already generated
                exists = conn.execute("SELECT id FROM notifications WHERE tender_id = ? AND type = 'expired';", (t_id,)).fetchone()
                if not exists:
                    conn.execute("""
                        INSERT INTO notifications (id, tender_id, reminder_id, title, message, type, is_read, created_at)
                        VALUES (?, ?, NULL, ?, ?, 'expired', 0, ?);
                    """, (
                        f"notif_exp_{t_id}",
                        t_id,
                        f"⚫ Submission Deadline Passed",
                        f'The submission deadline for "{t_title}" has passed.',
                        now_utc_str
                    ))
                    fired_count += 1
                    try:
                        print(f"[DeadlineScheduler] Marked tender expired: '{t_title}'")
                    except Exception:
                        pass

        return fired_count
