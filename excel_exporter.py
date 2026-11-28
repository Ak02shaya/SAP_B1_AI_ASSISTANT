import io
import os
import re
import logging
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from config import LIVE_QUERY_URL

load_dotenv()

logger = logging.getLogger(__name__)
router = APIRouter()

#COMPANY_API_URL = os.getenv("COMPANY_API_URL")
COMPANY_API_KEY = os.getenv("COMPANY_API_KEY", "YOUR_API_KEY")

hana_export_session = requests.Session()

FORBIDDEN_KEYWORDS = ["DROP ", "DELETE ", "UPDATE ", "INSERT ", "ALTER ", "EXEC ", "CREATE "]


class ExportExcelRequest(BaseModel):
    sql: str
    filename: str | None = None


def _clean_sap_value(val):
    """Converts SAP HANA 6-decimal numeric strings ('19337.000000') into real Excel numbers."""
    if val is None:
        return ""
    if isinstance(val, str) and re.fullmatch(r"-?\d+\.\d{6}", val.strip()):
        trimmed = val.strip().rstrip("0").rstrip(".")
        return int(trimmed) if "." not in trimmed else float(trimmed)
    return val


class ExportExcelRequest(BaseModel):
    sql: str
    filename: str | None = None
    question: str | None = None  # Add this


def _validate_and_prepare_sql(sql_query: str, question: str | None = None) -> str:
    clean_sql = sql_query.replace("```sql", "").replace("```", "").strip().rstrip(";")
    upper_sql = clean_sql.upper()

    if not upper_sql.startswith("SELECT") or any(k in upper_sql for k in FORBIDDEN_KEYWORDS):
        raise HTTPException(status_code=400, detail="Security Alert: Only SELECT queries are permitted.")
    #return re.sub(r"\s+LIMIT\s+100\b", "", clean_sql, flags=re.IGNORECASE) default value for strip
    # Only strip LIMIT 100 if the user didn't explicitly ask for 100
    user_asked_100 = bool(question and re.search(r"\b100\b", question))
    if not user_asked_100:
        clean_sql = re.sub(r"\s+LIMIT\s+100\b", "", clean_sql, flags=re.IGNORECASE)

    return clean_sql


def _fetch_full_hana_rows(sql_query: str) -> list[dict]:
    """Executes SQL directly against SAP HANA with NO row truncation."""
    headers = {
        "QIKCHAT-API-KEY": COMPANY_API_KEY,
        "Content-Type": "text/plain",
    }
    response = hana_export_session.post(
        LIVE_QUERY_URL,
        headers=headers,
        data=sql_query.encode("utf-8"),
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict) and any(k.lower() in ["error", "message", "errormessage"] for k in data.keys()):
        raise HTTPException(status_code=400, detail=f"SAP HANA Error: {data}")

    rows = data if isinstance(data, list) else data.get("value", data.get("results", []))
    return rows if isinstance(rows, list) else []

ID_COL_PATTERN = re.compile(
    r"(docnum|docentry|invoice|code|num|no$|_no\b|id$|_id\b|phone|mobile|year|pin|zip)",
    re.IGNORECASE,
)

def _style_worksheet(ws, df: pd.DataFrame):
    """Applies header styling, Indian number formatting, auto-filter, frozen header, and column widths."""
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)

    for col_idx, col_name in enumerate(df.columns, start=1):
        # 1. Style header
        header_cell = ws.cell(row=1, column=col_idx)
        header_cell.fill = header_fill
        header_cell.font = header_font
        header_cell.alignment = Alignment(horizontal="center", vertical="center")

        # 2. Apply Indian comma formatting to numeric columns (skip IDs / DocNums / Years)
        is_id_col = bool(ID_COL_PATTERN.search(str(col_name)))
        if not is_id_col and pd.api.types.is_numeric_dtype(df[col_name]):
            has_decimals = pd.api.types.is_float_dtype(df[col_name]) and (df[col_name].dropna() % 1 != 0).any()
            num_fmt = "[$-en-IN]#,##,##0.00" if has_decimals else "[$-en-IN]#,##,##0"

            for row_idx in range(2, len(df) + 2):
                cell = ws.cell(row=row_idx, column=col_idx)
                if isinstance(cell.value, (int, float)):
                    cell.number_format = num_fmt

        # 3. Auto-fit column width
        col_letter = get_column_letter(col_idx)
        max_len = max(
            [len(str(col_name))]
            + [len(str(v)) for v in df.iloc[:200, col_idx - 1]]
        )
        ws.column_dimensions[col_letter].width = min(max_len + 6, 45)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def build_excel_bytes(sql_block: str, question: str | None = None) -> io.BytesIO:
    """Splits one or more SQL queries, runs each on SAP HANA, and writes each to its own Excel tab."""
    raw_queries = [
        q.strip()
        for q in re.split(r"\n\s*\n(?=SELECT\b)", sql_block.strip(), flags=re.IGNORECASE)
        if q.strip()
    ]

    print("\n" + "=" * 60)
    print(f" EXCEL EXPORTER: Detected {len(raw_queries)} SQL query(s)")
    print("=" * 60)

    output = io.BytesIO()
    sheets_written = 0

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for idx, raw_q in enumerate(raw_queries, start=1):
            export_sql = _validate_and_prepare_sql(raw_q, question)

            print(f"\n--- [Query {idx}/{len(raw_queries)}] SQL Sent to SAP HANA ---")
            print(export_sql)

            rows = _fetch_full_hana_rows(export_sql)
            print(f"--- [Query {idx}/{len(raw_queries)}] Rows Returned: {len(rows)} ---")

            if not rows:
                print(f"Skipping Query {idx} (0 rows returned).")
                continue

            cleaned_rows = [{k: _clean_sap_value(v) for k, v in r.items()} for r in rows]
            df = pd.DataFrame(cleaned_rows)

            sheet_name = "SAP Report" if len(raw_queries) == 1 else f"Report {idx}"
            df.to_excel(writer, index=False, sheet_name=sheet_name)
            _style_worksheet(writer.sheets[sheet_name], df)
            sheets_written += 1

            print(f"Written to Excel Tab: '{sheet_name}' ({len(df)} rows x {len(df.columns)} cols)")

    print("=" * 60 + "\n")

    if sheets_written == 0:
        raise HTTPException(status_code=404, detail="No records found to export.")

    output.seek(0)
    return output


@router.post("/api/v1/export_excel")
def export_excel(request: ExportExcelRequest):
    """Zero-token endpoint: executes SQL directly against SAP HANA and streams an .xlsx file."""
    try:
        excel_buffer = build_excel_bytes(request.sql, request.question)
        filename = request.filename or f"SAP_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

        return StreamingResponse(
            excel_buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except requests.exceptions.RequestException as e:
        logger.error(f"SAP HANA Connection Error during Excel export: {e}")
        raise HTTPException(status_code=502, detail=f"SAP HANA connection failed: {str(e)}")
    except Exception as e:
        logger.error(f"Excel Export Error: {e}")
        raise HTTPException(status_code=500, detail=f"Excel export failed: {str(e)}")