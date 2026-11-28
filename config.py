import os
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("DB_URL", "").rstrip("/") + "/"
DB_API_KEY = os.getenv("COMPANY_API_KEY", "")


def build_url(path: str) -> str:
    """Safely appends an endpoint path to HANA_BASE_URL."""
    return urljoin(BASE_URL, path.lstrip("/"))


# Replace these relative paths with the exact paths your backend team gives you
LIVE_QUERY_URL  = build_url("GetDatas")                 # Live DB (business queries & Excel)
USER_AUTH_URL   = build_url("GetUserData")           # User DB (AI_USERS login)
CONV_SELECT_URL = build_url("GetLastDetails")  # User DB (AI_CONVERSATIONS select)
CONV_INSERT_URL = build_url("InsertRecord")  # User DB (AI_CONVERSATIONS insert)