"""
Conversation Cache for SAP B1 AI Assistant
-------------------------------------------
Stores per-session conversation history (session_id, role, content, summary, created_at).
All turns are kept until the user signs out, which triggers clear_session().
"""

import sqlite3
import time
import logging

logger = logging.getLogger(__name__)

DB_PATH = "copilot_cache.db"

RECENT_TURNS_WITH_DETAIL = 3
RECENT_SUMMARY_MAX_CHARS = 900
OLD_SUMMARY_MAX_CHARS = 300


def _ensure_column(cursor, table: str, column: str, ddl: str):
    """Adds a column to an existing table if it is missing."""
    cursor.execute(f"PRAGMA table_info({table})")
    existing = [row[1] for row in cursor.fetchall()]
    if column not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        logger.info(f"Added column {column} to {table}")


def init_conversation_db():
    """Creates the simplified conversation history table."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Conversation_History (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            summary TEXT DEFAULT NULL,
            created_at REAL NOT NULL
        )
    """)
    _ensure_column(cursor, "Conversation_History", "summary", "TEXT DEFAULT NULL")
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_session_id
        ON Conversation_History(session_id)
    """)
    conn.commit()
    conn.close()


def save_turn(
    session_id: str,
    role: str,
    content: str,
    summary: str = None,
    **_ignored,
):
    """Saves a single conversation turn. Extra kwargs (like sql_query) are safely ignored."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO Conversation_History
            (session_id, role, content, summary, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (session_id, role, content, summary, time.time()))
    conn.commit()
    conn.close()


def get_conversation_history(session_id: str) -> list[dict]:
    """Returns the conversation history for a session, oldest first."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT role, content, summary, created_at
        FROM Conversation_History
        WHERE session_id = ?
        ORDER BY created_at ASC, id ASC
    """, (session_id,))
    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "role": r[0],
            "content": r[1],
            "summary": r[2],
            "created_at": r[3],
        }
        for r in rows
    ]


def get_last_sql(session_id: str) -> str | None:
    """Kept as a no-op stub so existing imports in middleware.py do not break."""
    return None


def clear_session(session_id: str):
    """Clears all conversation history for a session."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM Conversation_History WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
    logger.info(f"Cleared conversation history for session: {session_id}")


def _clip(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def build_context_messages(session_id: str, current_question: str) -> list[dict]:
    """Builds the messages array for Claude using only the stored summaries."""
    history = get_conversation_history(session_id)

    assistant_positions = [i for i, t in enumerate(history) if t["role"] == "assistant"]
    recent_positions = set(assistant_positions[-RECENT_TURNS_WITH_DETAIL:])

    messages = []
    for i, turn in enumerate(history):
        if turn["role"] != "assistant":
            messages.append({"role": "user", "content": turn["content"]})
            continue

        answer = turn.get("summary") or turn["content"]
        limit = RECENT_SUMMARY_MAX_CHARS if i in recent_positions else OLD_SUMMARY_MAX_CHARS
        messages.append({"role": "assistant", "content": "Answer given:\n" + _clip(answer, limit)})

    messages.append({"role": "user", "content": current_question})
    return messages