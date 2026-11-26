import os
import requests
from dotenv import load_dotenv

load_dotenv()

COMPANY_API_URL = os.getenv("COMPANY_API_URL")
COMPANY_API_KEY = os.getenv("COMPANY_API_KEY")

if not COMPANY_API_URL:
    print("ERROR: COMPANY_API_URL is missing from your .env file.")
    exit()

test_session = requests.Session()
headers = {
    "QIKCHAT-API-KEY": COMPANY_API_KEY,
    "Content-Type": "text/plain",
}


def run_query(sql: str):
    response = test_session.post(
        COMPANY_API_URL,
        headers=headers,
        data=sql.encode("utf-8"),
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list):
        return data
    return data.get("value", data.get("results", []))


print(" Testing SAP HANA API Row Limit...\n")

try:
    # 1. Check actual total rows available in INV1
    count_rows = run_query('SELECT COUNT(*) AS "Total_Rows" FROM "INV1"')
    actual_total = list(count_rows[0].values())[0] if count_rows else 0
    print(f"1️⃣ Actual rows in SAP HANA (INV1): {actual_total}")

    # 2. Fetch without any LIMIT clause
    uncapped_rows = run_query('SELECT "DocEntry" FROM "INV1"')
    print(f"2️⃣ Rows returned with NO LIMIT:     {len(uncapped_rows)}")

    # 3. Fetch with an explicit LIMIT 6000
    limit_6000_rows = run_query('SELECT "DocEntry" FROM "INV1" LIMIT 6000')
    print(f"3️⃣ Rows returned with LIMIT 6000:   {len(limit_6000_rows)}")

    print("\n" + "=" * 55)
    if actual_total > 5000 and len(uncapped_rows) == 5000:
        print(" VERDICT: SERVER-SIDE CAP CONFIRMED.")
        print("  Your SAP HANA API gateway caps every response at 5,000 rows.")
    elif actual_total <= 5000:
        print(f" VERDICT: Table only has {actual_total} rows (test on a larger table like OITM or OINM).")
    else:
        print(f" VERDICT: No 5,000-row server cap! API returned {len(uncapped_rows)} rows.")
    print("=" * 55)

except requests.exceptions.RequestException as e:
    print(f"\n Network/API Error: {e}")
except Exception as e:
    print(f"\n Unexpected Error: {e}")