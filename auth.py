import os
import hmac
import requests
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config import USER_AUTH_URL, DB_API_KEY

load_dotenv()

router = APIRouter()


USER_DB = os.getenv("HANA_USER_SCHEMA") #GETTING USER_DB
USER_TABLE = os.getenv("HANA_USER_TABLE")  #GETTING USER_TABLE

hana_auth_session = requests.Session()


class LoginRequest(BaseModel):
    username: str
    password: str


def authenticate_user(username: str, password: str) -> int | str | None:
    """Verifies U_NAME and U_PASSWORD against SAP HANA and returns U_ID if valid."""
    safe_user = username.strip().replace("'", "''")

    sql = f'''
        SELECT "U_ID", "U_NAME", "U_PASSWORD"
        FROM "{USER_DB}"."{USER_TABLE}"
        WHERE "U_NAME" = '{safe_user}'
        LIMIT 1
    '''

    headers = {
        "QIKCHAT-API-KEY": DB_API_KEY,
        "Content-Type": "application/json",
    }

    response = hana_auth_session.get(
        USER_AUTH_URL,
        headers=headers,
        data=sql.encode("utf-8"),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    rows = data if isinstance(data, list) else data.get("value", data.get("results", []))
    if not rows or not isinstance(rows, list):
        return None

    stored_password = str(rows[0].get("U_PASSWORD") or "")
    if hmac.compare_digest(stored_password, password):
        return rows[0].get("U_ID")
    return None


@router.post("/api/v1/login")
def login(request: LoginRequest):
    if not request.username.strip() or not request.password:
        raise HTTPException(status_code=400, detail="Username and password are required.")

    try:
        u_id = authenticate_user(request.username, request.password)
        if u_id is not None:
            return {
                "status": "success",
                "U_ID": u_id,
                "username": request.username.strip(),
            }
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Database connection error: {str(e)}")

    raise HTTPException(status_code=401, detail="Invalid username or password.")