import os
import hmac
import requests
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

load_dotenv()

router = APIRouter()

COMPANY_API_URL = os.getenv("COMPANY_API_URL")
COMPANY_API_KEY = os.getenv("COMPANY_API_KEY")
HANA_SCHEMA = os.getenv("HANA_SCHEMA_NAME")
USER_TABLE = os.getenv("HANA_USER_TABLE")  

hana_auth_session = requests.Session()


class LoginRequest(BaseModel):
    username: str
    password: str


def authenticate_user(username: str, password: str) -> bool:
    """Verifies U_NAME and U_PASSWORD against SAP HANA."""
    # Escape single quotes to prevent SQL injection
    safe_user = username.strip().replace("'", "''")

    sql = f'''
        SELECT "U_NAME", "U_PASSWORD"
        FROM "{HANA_SCHEMA}"."{USER_TABLE}"
        WHERE "U_NAME" = '{safe_user}'
        LIMIT 1
    '''

    headers = {
        "QIKCHAT-API-KEY": COMPANY_API_KEY,
        "Content-Type": "text/plain",
    }

    response = hana_auth_session.post(
        COMPANY_API_URL,
        headers=headers,
        data=sql.encode("utf-8"),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    rows = data if isinstance(data, list) else data.get("value", data.get("results", []))
    if not rows or not isinstance(rows, list):
        return False

    stored_password = str(rows[0].get("U_PASSWORD") or "")
    return hmac.compare_digest(stored_password, password)


@router.post("/api/v1/login")
def login(request: LoginRequest):
    if not request.username.strip() or not request.password:
        raise HTTPException(status_code=400, detail="Username and password are required.")

    try:
        if authenticate_user(request.username, request.password):
            return {"status": "success", "username": request.username.strip()}
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Database connection error: {str(e)}")

    raise HTTPException(status_code=401, detail="Invalid username or password.")