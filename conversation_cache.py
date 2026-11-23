"""
Conversation Cache for SAP B1 AI Assistant
-------------------------------------------
Stores per-session conversation history so Claude can follow the user's
continuous interaction flow. All turns are kept until the user signs out,
which triggers clear_session() to wipe the history.

Storage: SQLite (same DB as query cache). No auto-expiry — cleared on sign-out only.
"""

import sqlite3
import json
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = "copilot_cache.db"


def init_conversation_db():
    """Creates the conversation history table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Conversation_History (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            sql_query TEXT DEFAULT NULL,
            created_at REAL NOT NULL
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_session_id
        ON Conversation_History(session_id)
    """)
    conn.commit()
    conn.close()


def save_turn(session_id: str, role: str, content: str, sql_query: str = None):
    """Saves a single conversation turn. All turns are kept until sign-out."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = time.time()

    cursor.execute("""
        INSERT INTO Conversation_History (session_id, role, content, sql_query, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (session_id, role, content, sql_query, now))

    conn.commit()
    conn.close()


def get_conversation_history(session_id: str) -> list[dict]:
    """
    Returns the full conversation history for a session as a list of
    {"role": ..., "content": ..., "sql_query": ...} dicts, ordered oldest-first.
    History persists until the user signs out and clear_session() is called.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Fetch all turns for this session
    cursor.execute("""
        SELECT role, content, sql_query FROM Conversation_History
        WHERE session_id = ?
        ORDER BY created_at ASC
    """, (session_id,))

    rows = cursor.fetchall()
    conn.close()

    return [{"role": row[0], "content": row[1], "sql_query": row[2]} for row in rows]


def get_last_sql(session_id: str) -> str | None:
    """Returns the most recent SQL query from this session, or None."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sql_query FROM Conversation_History
        WHERE session_id = ? AND sql_query IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 1
    """, (session_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


def clear_session(session_id: str):
    """Clears all conversation history for a session."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM Conversation_History WHERE session_id = ?
    """, (session_id,))
    conn.commit()
    conn.close()
    logger.info(f"Cleared conversation history for session: {session_id}")


def build_context_messages(session_id: str, current_question: str) -> list[dict]:
    """
    Builds the full messages array for Claude:
    - Past conversation turns (with SQL executed and answer summary) for continuous multi-turn memory
    - Current user question (always last)

    This is the main function the middleware should call.
    """
    history = get_conversation_history(session_id)

    context_messages = []

    for turn in history:
        role = turn["role"]
        content = turn["content"]
        sql_query = turn.get("sql_query")

        if role == "assistant":
            # If a SQL query was associated with this turn, preserve it so Claude knows what was queried
            if sql_query:
                assistant_text = f"[Executed SQL]:\n{sql_query}\n\n[Answer]:\n{content}"
            else:
                assistant_text = content
            
            # Keep reasonable length limit to preserve token budget
            if len(assistant_text) > 800:
                assistant_text = assistant_text[:800] + "..."
            context_messages.append({"role": "assistant", "content": assistant_text})
        else:
            context_messages.append({"role": "user", "content": content})

    # Add the current question
    context_messages.append({"role": "user", "content": current_question})

    return context_messages
