import os
import re
import requests
from datetime import datetime
from dotenv import load_dotenv
from config import CONV_SELECT_URL, CONV_INSERT_URL, DB_API_KEY

try:
    import yake
    _KW_EXTRACTOR = yake.KeywordExtractor(lan="en", n=3, dedupLim=0.7, top=2)
except ImportError:
    _KW_EXTRACTOR = None

load_dotenv()

HANA_USER_SCHEMA = os.getenv("HANA_USER_SCHEMA")
CONV_TABLE = os.getenv("HANA_USER_CONVERSATION")
DEFAULT_CONTEXT_N = int(os.getenv("CONVERSATION_CONTEXT_N", "10"))

HEADERS = {
    "Content-Type": "application/json",
    "QIKCHAT-API-KEY": "DB_API_KEY" ,
}


_FILLER_PREFIXES = (
    r"^(please\s+)?(can\s+you\s+|could\s+you\s+|would\s+you\s+)?"
    r"(give\s+me|give|show\s+me|show|get\s+me|get|tell\s+me|tell|"
    r"find\s+me|find|list|fetch|display|what\s+is|what\s+are|what|"
    r"how\s+much\s+is|how\s+many|how)\s+(the\s+|a\s+|an\s+|all\s+)?"
)


def extract_chat_title(question: str, max_words: int = 5) -> str:
    """Generates a short CHAT_TITLE from the first question."""
    text = re.sub(r"[^\w\s₹\-/]", " ", (question or "").strip())
    core = re.sub(_FILLER_PREFIXES, "", re.sub(r"\s+", " ", text), flags=re.IGNORECASE).strip() or text

    if _KW_EXTRACTOR is not None:
        keywords = _KW_EXTRACTOR.extract_keywords(core)
        if keywords:
            return keywords[0][0].strip().title()

    return " ".join(core.split()[:max_words]).title() or "New Chat"


def get_conversation_history(u_id: int, chat_id: int, n: int | None = None) -> list[dict]:
    """
    Fetches the last N pairs (N * 2 rows) strictly for this U_ID and CHAT_ID.
    User 1 (U_ID=1) can never read User 2's (U_ID=2) rows.
    """
    row_limit = (n if n is not None else DEFAULT_CONTEXT_N) * 2
    payload = {
        "table": f"{HANA_USER_SCHEMA}.{CONV_TABLE}",
        "U_ID": u_id,
        "CHAT_ID": chat_id,
        "limit": row_limit,
    }
    resp = requests.get(CONV_SELECT_URL, json=payload, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    rows = data if isinstance(data, list) else data.get("data", data.get("results", []))
    # Sort oldest -> newest so Claude reads the conversation in order
    rows.sort(key=lambda r: (r.get("QUES_ID", 0), 0 if str(r.get("ROLE", "")).lower() == "user" else 1))
    return rows[-row_limit:] if row_limit > 0 else []


def build_context_messages(u_id: int, chat_id: int, current_question: str, n: int | None = None) -> list[dict]:
    """Converts fetched HANA rows into Claude's messages list."""
    rows = get_conversation_history(u_id=u_id, chat_id=chat_id, n=n)
    messages = []

    for row in rows:
        role = str(row.get("ROLE") or "user").lower()
        context = row.get("CONTEXT") or ""
        messages.append({"role": role, "content": context})

    messages.append({"role": "user", "content": current_question})
    return messages


def insert_conversation_turn(
    u_id: int,
    chat_id: int,
    ques_id: int,
    question: str,
    summary: str,
    chat_title: str | None = None,
) -> str:
    """
    Inserts 2 rows (user + assistant) under this U_ID and CHAT_ID.
    Returns the CHAT_TITLE so the session can reuse it for subsequent questions.
    """
    title = chat_title if (chat_title and ques_id > 1) else extract_chat_title(question)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = [
        {
            "table": f"{HANA_USER_SCHEMA}.{CONV_TABLE}",
            "U_ID": u_id,
            "CHAT_ID": chat_id,
            "CHAT_TITLE": title,
            "QUES_ID": ques_id,
            "ROLE": "user",
            "CONTEXT": question,
            "CREATED_AT": created_at,
        },
        {
            "table": f"{HANA_USER_SCHEMA}.{CONV_TABLE}",
            "U_ID": u_id,
            "CHAT_ID": chat_id,
            "CHAT_TITLE": title,
            "QUES_ID": ques_id,
            "ROLE": "assistant",
            "CONTEXT": summary,
            "CREATED_AT": created_at,
        },
    ]

    for payload in rows:
        resp = requests.post(CONV_INSERT_URL, params=payload, headers=HEADERS, timeout=15)

        if resp.status_code != 200:
             print("GetLastDetails 400 Body:", resp.text, flush=True)

        resp.raise_for_status()

    return title