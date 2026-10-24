"""SQLite connection, schema, and CRUD helpers for Whose?.

Business logic only — no Streamlit imports. The hidden detail is isolated: every read used for
display, search, or AI selects an explicit column list that omits `hidden_detail`. The single
`get_hidden_detail` helper is the only read that returns it, used solely by verify.py.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

# Database file location: data/whose.db relative to the project root.
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(_DATA_DIR, "whose.db")

# Item lifecycle statuses.
STATUS_UNCLAIMED = "unclaimed"
STATUS_PENDING = "pending_pickup"
STATUS_RETRIEVED = "retrieved"

# Holder types.
HOLDER_LOCATION = "location"
HOLDER_FINDER = "finder"

# Public column list for items. Deliberately excludes `hidden_detail` so no display, search,
# or AI read can ever leak it. Keep this in sync with the schema (minus hidden_detail).
PUBLIC_ITEM_COLUMNS = (
    "id",
    "created_at",
    "status",
    "archived",
    "where_found",
    "holder_type",
    "location_id",
    "finder_contact",
    "handoff_code",
    "image_path",
    "description",
    "tags",
    "primary_type",
    "sensitive",
    "high_value",
    "flagged_for_review",
    "short_description",
    "retrieved_at",
    "retrieved_by_claimant_id",
)

_PUBLIC_COLS_SQL = ", ".join(PUBLIC_ITEM_COLUMNS)


def _now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    """Open a SQLite connection with row access by name and FK enforcement."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> None:
    """Create the schema if it does not exist. Idempotent."""
    own = conn is None
    conn = conn or get_conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                where_found TEXT,
                holder_type TEXT NOT NULL,
                location_id TEXT,
                finder_contact TEXT,
                handoff_code TEXT,
                image_path TEXT,
                description TEXT,
                tags TEXT,
                primary_type TEXT,
                sensitive INTEGER NOT NULL DEFAULT 0,
                high_value INTEGER NOT NULL DEFAULT 0,
                hidden_detail TEXT,
                flagged_for_review INTEGER NOT NULL DEFAULT 0,
                short_description TEXT,
                retrieved_at TEXT,
                retrieved_by_claimant_id INTEGER
                    REFERENCES verified_claimants(id)
            );

            CREATE TABLE IF NOT EXISTS verified_claimants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES items(id),
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                verified_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS verification_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES items(id),
                email TEXT NOT NULL,
                attempted_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
            CREATE INDEX IF NOT EXISTS idx_claimants_item ON verified_claimants(item_id);
            CREATE INDEX IF NOT EXISTS idx_attempts_item_email
                ON verification_attempts(item_id, email);
            """
        )
        conn.commit()
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
# Item CRUD (hidden-detail isolated)
# ---------------------------------------------------------------------------


def insert_item(
    conn: sqlite3.Connection,
    *,
    where_found: str,
    holder_type: str,
    hidden_detail: str,
    location_id: str | None = None,
    finder_contact: str | None = None,
    handoff_code: str | None = None,
    image_path: str | None = None,
    description: str = "",
    tags: Iterable[str] | None = None,
    primary_type: str | None = None,
    sensitive: bool = False,
    high_value: bool = False,
    short_description: str | None = None,
    status: str = STATUS_UNCLAIMED,
) -> int:
    """Insert a new item and return its id. Status defaults to unclaimed.

    `primary_type` is the main item category (e.g. "laptop", "water bottle"), used to give
    a ranking boost when an owner's search names that type. Optional; may be None.
    """
    cur = conn.execute(
        """
        INSERT INTO items (
            created_at, status, archived, where_found, holder_type, location_id,
            finder_contact, handoff_code, image_path, description, tags, primary_type,
            sensitive, high_value, hidden_detail, flagged_for_review,
            short_description, retrieved_at, retrieved_by_claimant_id
        ) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, NULL)
        """,
        (
            _now(),
            status,
            where_found,
            holder_type,
            location_id,
            finder_contact,
            handoff_code,
            image_path,
            description,
            json.dumps(list(tags) if tags else []),
            primary_type,
            1 if sensitive else 0,
            1 if high_value else 0,
            hidden_detail,
            short_description,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_item(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    """Return one item by id without the hidden detail, or None."""
    return conn.execute(
        f"SELECT {_PUBLIC_COLS_SQL} FROM items WHERE id = ?", (item_id,)
    ).fetchone()


def get_hidden_detail(conn: sqlite3.Connection, item_id: int) -> str | None:
    """Return the hidden detail for an item. The ONLY read of this column.

    Intended for verify.py only. Never surface the result in any view.
    """
    row = conn.execute(
        "SELECT hidden_detail FROM items WHERE id = ?", (item_id,)
    ).fetchone()
    return row["hidden_detail"] if row else None


def list_items_for_search(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All non-archived items for ranking, without the hidden detail."""
    return conn.execute(
        f"SELECT {_PUBLIC_COLS_SQL} FROM items WHERE archived = 0 "
        "ORDER BY created_at DESC"
    ).fetchall()


def list_pending_items(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Non-archived items in pending_pickup for the desk view, without hidden detail."""
    return conn.execute(
        f"SELECT {_PUBLIC_COLS_SQL} FROM items "
        "WHERE status = ? AND archived = 0 ORDER BY created_at ASC",
        (STATUS_PENDING,),
    ).fetchall()


def count_claimable_items(conn: sqlite3.Connection) -> int:
    """Count non-archived items still waiting to be claimed (unclaimed or pending)."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM items "
        "WHERE archived = 0 AND status IN (?, ?)",
        (STATUS_UNCLAIMED, STATUS_PENDING),
    ).fetchone()
    return int(row["n"])


def count_retrieved_items(conn: sqlite3.Connection) -> int:
    """Count items that have been returned (retrieved), including archived ones."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM items WHERE status = ?",
        (STATUS_RETRIEVED,),
    ).fetchone()
    return int(row["n"])


def list_recent_unclaimed_public(
    conn: sqlite3.Connection, limit: int = 4
) -> list[sqlite3.Row]:
    """Newest non-archived, non-sensitive, unclaimed items for the home preview.

    Excludes sensitive items (no photo shown publicly) and the hidden detail. Only
    `unclaimed` items appear here so the preview highlights things nobody has started
    claiming yet.
    """
    return conn.execute(
        f"SELECT {_PUBLIC_COLS_SQL} FROM items "
        "WHERE archived = 0 AND sensitive = 0 AND status = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (STATUS_UNCLAIMED, int(limit)),
    ).fetchall()


def list_retrieved_items(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Non-archived retrieved items for the desk's archive action, without hidden detail."""
    return conn.execute(
        f"SELECT {_PUBLIC_COLS_SQL} FROM items "
        "WHERE status = ? AND archived = 0 ORDER BY retrieved_at DESC",
        (STATUS_RETRIEVED,),
    ).fetchall()


def set_status(conn: sqlite3.Connection, item_id: int, status: str) -> None:
    """Set an item's lifecycle status."""
    conn.execute("UPDATE items SET status = ? WHERE id = ?", (status, item_id))
    conn.commit()


def mark_retrieved(
    conn: sqlite3.Connection, item_id: int, claimant_id: int | None
) -> None:
    """Mark an item retrieved, recording the claimant (or None) and the time."""
    conn.execute(
        "UPDATE items SET status = ?, retrieved_at = ?, "
        "retrieved_by_claimant_id = ? WHERE id = ?",
        (STATUS_RETRIEVED, _now(), claimant_id, item_id),
    )
    conn.commit()


def archive_item(conn: sqlite3.Connection, item_id: int) -> None:
    """Archive an item so it drops out of search results and active desk lists."""
    conn.execute("UPDATE items SET archived = 1 WHERE id = ?", (item_id,))
    conn.commit()


def set_flagged_for_review(conn: sqlite3.Connection, item_id: int) -> None:
    """Flag an item for desk review (per-item failed-attempt cap reached)."""
    conn.execute(
        "UPDATE items SET flagged_for_review = 1 WHERE id = ?", (item_id,)
    )
    conn.commit()


def find_item_by_handoff_code(
    conn: sqlite3.Connection, code: str
) -> sqlite3.Row | None:
    """Find a non-retrieved item by its handoff code, without hidden detail.

    Matching is case-insensitive and trims surrounding whitespace so a finder can type
    the code without worrying about case.
    """
    normalized = (code or "").strip()
    if not normalized:
        return None
    return conn.execute(
        f"SELECT {_PUBLIC_COLS_SQL} FROM items "
        "WHERE handoff_code IS NOT NULL "
        "AND UPPER(handoff_code) = UPPER(?) AND status != ?",
        (normalized, STATUS_RETRIEVED),
    ).fetchone()


# ---------------------------------------------------------------------------
# Verified claimants and attempts
# ---------------------------------------------------------------------------


def add_verified_claimant(
    conn: sqlite3.Connection, item_id: int, name: str, email: str
) -> int:
    """Record a claimant who passed the hidden-detail check. Returns the claimant id."""
    cur = conn.execute(
        "INSERT INTO verified_claimants (item_id, name, email, verified_at) "
        "VALUES (?, ?, ?, ?)",
        (item_id, name, email, _now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_claimants(conn: sqlite3.Connection, item_id: int) -> list[sqlite3.Row]:
    """All verified claimants for an item, newest first."""
    return conn.execute(
        "SELECT id, item_id, name, email, verified_at FROM verified_claimants "
        "WHERE item_id = ? ORDER BY verified_at DESC",
        (item_id,),
    ).fetchall()


def record_failed_attempt(
    conn: sqlite3.Connection, item_id: int, email: str
) -> None:
    """Record one failed verification attempt for an item and email (lowercased)."""
    conn.execute(
        "INSERT INTO verification_attempts (item_id, email, attempted_at) "
        "VALUES (?, ?, ?)",
        (item_id, (email or "").strip().lower(), _now()),
    )
    conn.commit()


def count_attempts(
    conn: sqlite3.Connection, item_id: int, email: str | None = None
) -> int:
    """Count failed attempts for an item.

    With an email, counts failures for that email on this item (per-email lock check).
    Without an email, counts all failures for the item (per-item desk-review cap check).
    """
    if email is None:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM verification_attempts WHERE item_id = ?",
            (item_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM verification_attempts "
            "WHERE item_id = ? AND email = ?",
            (item_id, (email or "").strip().lower()),
        ).fetchone()
    return int(row["n"])


def item_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert an item row to a dict, decoding the tags JSON to a list."""
    data = dict(row)
    if "tags" in data:
        try:
            data["tags"] = json.loads(data["tags"]) if data["tags"] else []
        except (json.JSONDecodeError, TypeError):
            data["tags"] = []
    return data
