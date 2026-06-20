import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("/app/data/conversations.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            reasoning_trace TEXT,
            has_logic INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conv
            ON messages(conversation_id);
    """)
    conn.close()


def create_conversation(title: str = "New conversation") -> str:
    conv_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (conv_id, title, now, now),
    )
    conn.commit()
    conn.close()
    return conv_id


def update_conversation_title(conv_id: str, title: str):
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
        (title, now, conv_id),
    )
    conn.commit()
    conn.close()


def add_message(
    conv_id: str,
    role: str,
    content: str,
    reasoning_trace: list | None = None,
    has_logic: bool = False,
):
    now = datetime.now(timezone.utc).isoformat()
    trace_json = json.dumps(reasoning_trace) if reasoning_trace else None
    conn = _get_conn()
    conn.execute(
        """INSERT INTO messages
           (conversation_id, role, content, reasoning_trace, has_logic, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (conv_id, role, content, trace_json, int(has_logic), now),
    )
    conn.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (now, conv_id),
    )
    conn.commit()
    conn.close()


def list_conversations() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        """SELECT c.id, c.title, c.created_at, COUNT(m.id) as message_count
           FROM conversations c
           LEFT JOIN messages m ON m.conversation_id = c.id
           GROUP BY c.id
           ORDER BY c.updated_at DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_conversation(conv_id: str) -> dict | None:
    conn = _get_conn()
    conv = conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (conv_id,)
    ).fetchone()
    if not conv:
        conn.close()
        return None
    messages = conn.execute(
        "SELECT role, content, reasoning_trace, has_logic, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at",
        (conv_id,),
    ).fetchall()
    conn.close()
    return {
        "id": conv["id"],
        "title": conv["title"],
        "created_at": conv["created_at"],
        "messages": [
            {
                "role": m["role"],
                "content": m["content"],
                "reasoning_trace": json.loads(m["reasoning_trace"]) if m["reasoning_trace"] else None,
                "has_logic": bool(m["has_logic"]),
                "created_at": m["created_at"],
            }
            for m in messages
        ],
    }


def delete_conversation(conv_id: str):
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
    conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    conn.commit()
    conn.close()
