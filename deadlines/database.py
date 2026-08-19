"""
Tender Deadline & Reminder Persistence Layer.
Manages SQLite database for Tenders, Reminders, and Notifications.
Fully timezone-aware, persistent, thread-safe, and self-contained.
"""

import os
import sqlite3
import uuid
import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional
from config import TEMP_FOLDER

DB_DIR = os.path.join(TEMP_FOLDER, "deadlines")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "tendermind_deadlines.db")

DEFAULT_TIMEZONE = "Asia/Karachi"

# Default reminder offsets (before deadline): only 3 days and 1 day before by default
DEFAULT_REMINDER_OFFSETS = [
    {"offset": "7d", "label": "7 days before", "hours": 24 * 7, "enabled": False},
    {"offset": "3d", "label": "3 days before", "hours": 24 * 3, "enabled": True},
    {"offset": "24h", "label": "1 day (24 hours) before", "hours": 24, "enabled": True},
    {"offset": "6h", "label": "6 hours before", "hours": 6, "enabled": False},
    {"offset": "1h", "label": "1 hour before", "hours": 1, "enabled": False}
]

def get_db_connection() -> sqlite3.Connection:
    """Returns a SQLite connection with row factory enabled."""
    conn = sqlite3.connect(DB_PATH, timeout=20.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initializes the database schema if not already present."""
    with get_db_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS tenders (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            organization TEXT DEFAULT 'Not specified',
            file_name TEXT,
            upload_date TEXT,
            submission_deadline TEXT NOT NULL,
            submission_deadline_utc TEXT NOT NULL,
            opening_datetime TEXT,
            opening_datetime_utc TEXT,
            timezone TEXT DEFAULT 'Asia/Karachi',
            submission_deadline_source_page INTEGER DEFAULT 1,
            status TEXT DEFAULT 'UPCOMING',
            detected_raw TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_tenders_deadline_utc ON tenders(submission_deadline_utc);
        CREATE INDEX IF NOT EXISTS idx_tenders_status ON tenders(status);

        CREATE TABLE IF NOT EXISTS reminders (
            id TEXT PRIMARY KEY,
            tender_id TEXT NOT NULL,
            reminder_time_utc TEXT NOT NULL,
            reminder_offset TEXT NOT NULL,
            reminder_label TEXT NOT NULL,
            notification_type TEXT DEFAULT 'in_app',
            sent INTEGER DEFAULT 0,
            sent_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_reminders_pending ON reminders(sent, reminder_time_utc);
        CREATE INDEX IF NOT EXISTS idx_reminders_tender ON reminders(tender_id);

        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            tender_id TEXT,
            reminder_id TEXT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT DEFAULT 'info',
            is_read INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(is_read, created_at);
        """)

# Initialize on import
init_db()

class TimezoneHelper:
    """Helper for timezone conversions and ISO-8601 formatting."""

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def now_utc_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def parse_iso(dt_str: str) -> Optional[datetime]:
        """Safely parses ISO datetime string to timezone-aware datetime."""
        if not dt_str:
            return None
        try:
            # Replace Z with +00:00 for fromisoformat compatibility
            clean_str = dt_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_str)
            if dt.tzinfo is None:
                # If naive, assume default timezone
                dt = dt.replace(tzinfo=ZoneInfo(DEFAULT_TIMEZONE))
            return dt
        except Exception:
            return None

    @staticmethod
    def to_utc_iso(dt_str: str, tz_name: str = DEFAULT_TIMEZONE) -> Optional[str]:
        """Converts local datetime string to UTC ISO string."""
        if not dt_str:
            return None
        try:
            dt = TimezoneHelper.parse_iso(dt_str)
            if not dt:
                # Try parsing standard formats
                for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        naive = datetime.strptime(dt_str, fmt)
                        dt = naive.replace(tzinfo=ZoneInfo(tz_name))
                        break
                    except ValueError:
                        continue
            if dt:
                utc_dt = dt.astimezone(timezone.utc)
                return utc_dt.isoformat()
        except Exception:
            pass
        return None

    @staticmethod
    def to_local_display(utc_iso: str, tz_name: str = DEFAULT_TIMEZONE) -> Dict[str, str]:
        """Formats UTC ISO to local date, time, and human-readable string."""
        if not utc_iso:
            return {"date": "", "time": "", "formatted": "Not specified", "iso": ""}
        try:
            dt = TimezoneHelper.parse_iso(utc_iso)
            if dt:
                local_dt = dt.astimezone(ZoneInfo(tz_name))
                return {
                    "date": local_dt.strftime("%d %B %Y"),
                    "time": local_dt.strftime("%I:%M %p"),
                    "formatted": local_dt.strftime("%d %B %Y • %I:%M %p"),
                    "iso": local_dt.isoformat()
                }
        except Exception:
            pass
        return {"date": "", "time": "", "formatted": utc_iso, "iso": utc_iso}


class DeadlineDB:
    """High-level DAO interface for Tenders, Reminders, and Notifications."""

    @classmethod
    def save_tender_deadline(
        cls,
        tender_id: str,
        title: str,
        organization: str,
        submission_deadline: str,
        tz_name: str = DEFAULT_TIMEZONE,
        file_name: str = None,
        opening_datetime: str = None,
        source_page: int = 1,
        reminder_config: List[Dict[str, Any]] = None,
        custom_reminders: List[Dict[str, Any]] = None,
        notification_channels: List[str] = None,
        detected_raw: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Creates or updates a tender deadline, calculates reminder schedules,
        and replaces any unsent reminders deterministically.
        """
        now_utc_str = TimezoneHelper.now_utc_iso()
        deadline_utc_str = TimezoneHelper.to_utc_iso(submission_deadline, tz_name)
        if not deadline_utc_str:
            raise ValueError(f"Invalid submission deadline format: {submission_deadline}")

        opening_utc_str = TimezoneHelper.to_utc_iso(opening_datetime, tz_name) if opening_datetime else None

        # Determine initial dynamic status
        deadline_dt = TimezoneHelper.parse_iso(deadline_utc_str)
        now_dt = TimezoneHelper.now_utc()
        if deadline_dt < now_dt:
            status = "EXPIRED"
        elif (deadline_dt - now_dt).total_seconds() <= 86400:
            status = "DUE_SOON"
        else:
            status = "UPCOMING"

        # Sanitize detected_raw before JSON serialization:
        # Remove internal debug fields that contain datetime objects or circular refs
        _SKIP_KEYS = {"candidates", "all_candidates", "date_dt"}
        def _sanitize(obj):
            if isinstance(obj, dict):
                return {k: _sanitize(v) for k, v in obj.items() if k not in _SKIP_KEYS}
            if isinstance(obj, list):
                return [_sanitize(i) for i in obj]
            if isinstance(obj, datetime):
                return obj.isoformat()
            return obj
        detected_raw_json = json.dumps(_sanitize(detected_raw or {}), ensure_ascii=False)

        with get_db_connection() as conn:
            # Insert or update tender
            conn.execute("""
            INSERT INTO tenders (
                id, title, organization, file_name, upload_date,
                submission_deadline, submission_deadline_utc,
                opening_datetime, opening_datetime_utc,
                timezone, submission_deadline_source_page,
                status, detected_raw, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                organization = excluded.organization,
                file_name = COALESCE(excluded.file_name, tenders.file_name),
                submission_deadline = excluded.submission_deadline,
                submission_deadline_utc = excluded.submission_deadline_utc,
                opening_datetime = excluded.opening_datetime,
                opening_datetime_utc = excluded.opening_datetime_utc,
                timezone = excluded.timezone,
                submission_deadline_source_page = excluded.submission_deadline_source_page,
                status = excluded.status,
                detected_raw = excluded.detected_raw,
                updated_at = excluded.updated_at;
            """, (
                tender_id, title, organization or "Not specified", file_name,
                now_utc_str, submission_deadline, deadline_utc_str,
                opening_datetime, opening_utc_str,
                tz_name, source_page, status, detected_raw_json,
                now_utc_str, now_utc_str
            ))

            # Delete any existing unsent reminders for this tender (cancel obsolete)
            conn.execute("DELETE FROM reminders WHERE tender_id = ? AND sent = 0;", (tender_id,))

            # Generate and insert new reminders
            reminders_to_insert = cls._build_reminders_list(
                tender_id=tender_id,
                deadline_dt=deadline_dt,
                reminder_config=reminder_config,
                custom_reminders=custom_reminders,
                notification_channels=notification_channels or ["in_app", "browser"]
            )

            for rem in reminders_to_insert:
                conn.execute("""
                INSERT INTO reminders (
                    id, tender_id, reminder_time_utc, reminder_offset,
                    reminder_label, notification_type, sent, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?);
                """, (
                    rem["id"], rem["tender_id"], rem["reminder_time_utc"],
                    rem["reminder_offset"], rem["reminder_label"],
                    rem["notification_type"], now_utc_str
                ))

        return cls.get_tender_deadline(tender_id)

    @classmethod
    def _build_reminders_list(
        cls,
        tender_id: str,
        deadline_dt: datetime,
        reminder_config: Optional[List[Dict[str, Any]]],
        custom_reminders: Optional[List[Dict[str, Any]]],
        notification_channels: List[str]
    ) -> List[Dict[str, Any]]:
        """Calculates reminder trigger timestamps before deadline."""
        now_dt = TimezoneHelper.now_utc()
        reminders = []
        channels_str = ",".join(notification_channels)

        # Standard default offsets if config not provided
        configs = reminder_config if reminder_config is not None else DEFAULT_REMINDER_OFFSETS

        for cfg in configs:
            if not cfg.get("enabled", True):
                continue
            offset_code = cfg.get("offset")
            hours = cfg.get("hours", 0)
            label = cfg.get("label", f"{hours}h before")

            trigger_dt = deadline_dt - timedelta(hours=hours)
            # Only schedule reminders that have not already passed (or are due in the near future)
            if trigger_dt > now_dt - timedelta(minutes=5):
                reminders.append({
                    "id": str(uuid.uuid4()),
                    "tender_id": tender_id,
                    "reminder_time_utc": trigger_dt.isoformat(),
                    "reminder_offset": offset_code,
                    "reminder_label": label,
                    "notification_type": channels_str
                })

        # Process custom reminders (e.g. 2 hours / 4 days before)
        if custom_reminders:
            for cust in custom_reminders:
                if not cust.get("enabled", True):
                    continue
                val = float(cust.get("value", 1))
                unit = cust.get("unit", "hours").lower()
                hours = val * 24 if unit.startswith("day") else val
                label = f"{int(val) if val.is_integer() else val} {unit} before"
                offset_code = f"custom_{int(hours)}h"

                trigger_dt = deadline_dt - timedelta(hours=hours)
                if trigger_dt > now_dt - timedelta(minutes=5):
                    reminders.append({
                        "id": str(uuid.uuid4()),
                        "tender_id": tender_id,
                        "reminder_time_utc": trigger_dt.isoformat(),
                        "reminder_offset": offset_code,
                        "reminder_label": label,
                        "notification_type": channels_str
                    })

        return reminders

    @classmethod
    def get_tender_deadline(cls, tender_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single tender by ID with its reminders and dynamic remaining time."""
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM tenders WHERE id = ?;", (tender_id,)).fetchone()
            if not row:
                return None
            tender = dict(row)

            # Fetch reminders
            rem_rows = conn.execute(
                "SELECT * FROM reminders WHERE tender_id = ? ORDER BY reminder_time_utc ASC;",
                (tender_id,)
            ).fetchall()
            tender["reminders"] = [dict(r) for r in rem_rows]

            # Parse detected_raw
            if tender.get("detected_raw"):
                try:
                    tender["detected_raw"] = json.loads(tender["detected_raw"])
                except Exception:
                    tender["detected_raw"] = {}

            return cls._enrich_tender_state(tender)

    @classmethod
    def list_tenders(
        cls,
        filter_status: str = "all",
        search_query: str = None,
        sort_by: str = "nearest"
    ) -> List[Dict[str, Any]]:
        """
        Lists all saved tender deadlines with filtering, searching, and sorting.
        """
        query = "SELECT * FROM tenders WHERE 1=1"
        params = []

        if search_query:
            q_like = f"%{search_query.strip()}%"
            query += " AND (title LIKE ? OR organization LIKE ? OR file_name LIKE ?)"
            params.extend([q_like, q_like, q_like])

        # Sorting
        if sort_by == "nearest":
            query += " ORDER BY submission_deadline_utc ASC"
        elif sort_by == "latest_added":
            query += " ORDER BY created_at DESC"
        elif sort_by == "organization":
            query += " ORDER BY organization ASC"
        elif sort_by == "title":
            query += " ORDER BY title ASC"
        else:
            query += " ORDER BY submission_deadline_utc ASC"

        with get_db_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            tenders = []
            for r in rows:
                t = dict(r)
                # Count scheduled reminders
                rem_count = conn.execute(
                    "SELECT COUNT(*) FROM reminders WHERE tender_id = ? AND sent = 0;",
                    (t["id"],)
                ).fetchone()[0]
                t["pending_reminders_count"] = rem_count

                if t.get("detected_raw"):
                    try:
                        t["detected_raw"] = json.loads(t["detected_raw"])
                    except Exception:
                        t["detected_raw"] = {}

                enriched = cls._enrich_tender_state(t)

                # Filter by status category if requested
                if filter_status == "upcoming" and enriched["urgency"] == "expired":
                    continue
                elif filter_status == "due_soon" and enriched["urgency"] not in ("urgent", "orange", "yellow"):
                    continue
                elif filter_status == "expired" and enriched["urgency"] != "expired":
                    continue

                tenders.append(enriched)

            return tenders

    @classmethod
    def get_summary_counts(cls) -> Dict[str, int]:
        """Calculates dynamic KPI summary counts."""
        tenders = cls.list_tenders(filter_status="all")
        now_dt = TimezoneHelper.now_utc()

        due_tomorrow = 0
        due_this_week = 0
        upcoming = 0
        expired = 0

        for t in tenders:
            deadline_dt = TimezoneHelper.parse_iso(t["submission_deadline_utc"])
            if not deadline_dt:
                continue

            diff = (deadline_dt - now_dt).total_seconds()
            if diff <= 0:
                expired += 1
            elif diff <= 86400:
                due_tomorrow += 1
            elif diff <= 86400 * 7:
                due_this_week += 1
            else:
                upcoming += 1

        return {
            "due_tomorrow": due_tomorrow,
            "due_this_week": due_this_week,
            "upcoming": upcoming,
            "expired": expired,
            "total": len(tenders)
        }

    @classmethod
    def _enrich_tender_state(cls, tender: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates remaining seconds, urgency level, human countdown, and local display."""
        now_dt = TimezoneHelper.now_utc()
        deadline_dt = TimezoneHelper.parse_iso(tender.get("submission_deadline_utc"))
        tz_name = tender.get("timezone", DEFAULT_TIMEZONE)

        # Local display formatting
        tender["display"] = TimezoneHelper.to_local_display(tender.get("submission_deadline_utc"), tz_name)
        if tender.get("opening_datetime_utc"):
            tender["opening_display"] = TimezoneHelper.to_local_display(tender.get("opening_datetime_utc"), tz_name)
        else:
            tender["opening_display"] = {"formatted": "Not specified"}

        if not deadline_dt:
            tender["remaining_seconds"] = 0
            tender["remaining_human"] = "No deadline"
            tender["urgency"] = "gray"
            tender["urgency_text"] = "No deadline"
            tender["is_expired"] = False
            return tender

        diff_seconds = (deadline_dt - now_dt).total_seconds()
        tender["remaining_seconds"] = max(0, int(diff_seconds))
        tender["is_expired"] = diff_seconds <= 0

        if diff_seconds <= 0:
            tender["status"] = "DEADLINE_PASSED"
            tender["urgency"] = "expired"  # Gray
            tender["urgency_text"] = "Deadline passed"
            passed_seconds = abs(int(diff_seconds))
            if passed_seconds < 3600:
                tender["remaining_human"] = f"Passed {int(passed_seconds / 60)}m ago"
            elif passed_seconds < 86400:
                tender["remaining_human"] = f"Passed {int(passed_seconds / 3600)}h ago"
            else:
                tender["remaining_human"] = f"Passed {int(passed_seconds / 86400)}d ago"
        elif diff_seconds <= 6 * 3600:
            tender["status"] = "CRITICAL_DUE"
            tender["urgency"] = "urgent"  # Red
            hours = int(diff_seconds / 3600)
            mins = int((diff_seconds % 3600) / 60)
            tender["urgency_text"] = "Due today"
            tender["remaining_human"] = f"{hours}h {mins}m remaining" if hours > 0 else f"{mins}m remaining"
        elif diff_seconds <= 24 * 3600:
            tender["status"] = "DUE_SOON"
            tender["urgency"] = "orange"  # Orange
            hours = int(diff_seconds / 3600)
            mins = int((diff_seconds % 3600) / 60)
            tender["urgency_text"] = "Due tomorrow"
            tender["remaining_human"] = f"{hours}h {mins}m remaining"
        elif diff_seconds <= 3 * 86400:
            tender["status"] = "DUE_SOON"
            tender["urgency"] = "yellow"  # Yellow (1-3 days)
            days = int(diff_seconds / 86400)
            hours = int((diff_seconds % 86400) / 3600)
            tender["urgency_text"] = f"Due in {days} day{'s' if days > 1 else ''}"
            tender["remaining_human"] = f"{days}d {hours}h remaining"
        elif diff_seconds <= 7 * 86400:
            tender["status"] = "UPCOMING"
            tender["urgency"] = "blue"  # Blue (3-7 days)
            days = int(diff_seconds / 86400)
            tender["urgency_text"] = f"Due in {days} days"
            tender["remaining_human"] = f"{days} days remaining"
        else:
            tender["status"] = "UPCOMING"
            tender["urgency"] = "green"  # Green (>7 days)
            days = int(diff_seconds / 86400)
            tender["urgency_text"] = f"Due in {days} days"
            tender["remaining_human"] = f"{days} days remaining"

        return tender

    @classmethod
    def delete_tender_deadline(cls, tender_id: str) -> bool:
        """Deletes tender deadline and its scheduled reminders (preserves document PDF)."""
        with get_db_connection() as conn:
            conn.execute("DELETE FROM reminders WHERE tender_id = ?;", (tender_id,))
            res = conn.execute("DELETE FROM tenders WHERE id = ?;", (tender_id,))
            return res.rowcount > 0

    @classmethod
    def delete_all_tender_deadlines(cls) -> int:
        """Deletes all tender deadlines, scheduled reminders, and notifications."""
        with get_db_connection() as conn:
            conn.execute("DELETE FROM reminders;")
            conn.execute("DELETE FROM notifications;")
            res = conn.execute("DELETE FROM tenders;")
            return res.rowcount

    # --------------------------------------------------------------------------
    # Notifications Management
    # --------------------------------------------------------------------------
    @classmethod
    def create_notification(
        cls,
        title: str,
        message: str,
        tender_id: str = None,
        reminder_id: str = None,
        notif_type: str = "info"
    ) -> Dict[str, Any]:
        """Creates an in-app notification record."""
        notif_id = str(uuid.uuid4())
        now_utc = TimezoneHelper.now_utc_iso()

        with get_db_connection() as conn:
            conn.execute("""
            INSERT INTO notifications (id, tender_id, reminder_id, title, message, type, is_read, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?);
            """, (notif_id, tender_id, reminder_id, title, message, notif_type, now_utc))

        return {
            "id": notif_id,
            "tender_id": tender_id,
            "reminder_id": reminder_id,
            "title": title,
            "message": message,
            "type": notif_type,
            "is_read": 0,
            "created_at": now_utc
        }

    @classmethod
    def get_notifications(cls, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves list of notifications sorted by newest first."""
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?;",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    @classmethod
    def get_unread_notification_count(cls) -> int:
        """Returns total unread notification count for the badge."""
        with get_db_connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM notifications WHERE is_read = 0;").fetchone()
            return row[0] if row else 0

    @classmethod
    def mark_notifications_read(cls, notif_ids: List[str] = None):
        """Marks specific or all notifications as read."""
        with get_db_connection() as conn:
            if notif_ids:
                placeholders = ",".join("?" for _ in notif_ids)
                conn.execute(f"UPDATE notifications SET is_read = 1 WHERE id IN ({placeholders});", notif_ids)
            else:
                conn.execute("UPDATE notifications SET is_read = 1 WHERE is_read = 0;")

    @classmethod
    def clear_notifications(cls):
        """Clears all notification history."""
        with get_db_connection() as conn:
            conn.execute("DELETE FROM notifications;")
