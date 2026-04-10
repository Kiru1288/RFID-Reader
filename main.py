from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from datetime import datetime
from pydantic import BaseModel
import psycopg2
import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI()

print("\n🔥🔥🔥 SERVER STARTED 🔥🔥🔥")

# -------------------------------
# CORS
# -------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------
# DATABASE
# -------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    print("📡 Connecting to DB...")
    return psycopg2.connect(DATABASE_URL)

def init_db():
    print("🛠 Initializing DB...")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id SERIAL PRIMARY KEY,
        rfid_uid TEXT UNIQUE,
        first_name TEXT,
        last_name TEXT,
        phone TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id SERIAL PRIMARY KEY,
        rfid_uid TEXT,
        timestamp TEXT
    )
    """)

    conn.commit()
    conn.close()

    print("✅ DB READY")

init_db()

# -------------------------------
# GOOGLE SHEETS
# -------------------------------
client = None
SHEET_ID = "1-l4fz97lprWxAUcyNr3-pgsLGDIoEJS2TrNWHj7Cj-Q"

try:
    print("\n🌍 Setting up Google Sheets...")

    creds_json = os.getenv("GOOGLE_CREDENTIALS")

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    if creds_json:
        creds_dict = json.loads(creds_json)
        print("🔑 SERVICE ACCOUNT:", creds_dict.get("client_email"))
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

    elif os.path.exists("credentials.json"):
        with open("credentials.json") as f:
            creds_dict = json.load(f)
        print("🔑 SERVICE ACCOUNT:", creds_dict.get("client_email"))
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)

    print("✅ GOOGLE SHEETS CONNECTED")

except Exception as e:
    print("❌ GOOGLE ERROR:", str(e))

# -------------------------------
# 🔥 FIX: AUTO EXPAND SHEET
# -------------------------------
def ensure_sheet_size(sheet, min_cols=200, min_rows=1000):
    current_cols = sheet.col_count
    current_rows = sheet.row_count

    if current_cols < min_cols:
        print(f"📏 Expanding columns → {min_cols}")
        sheet.add_cols(min_cols - current_cols)

    if current_rows < min_rows:
        print(f"📏 Expanding rows → {min_rows}")
        sheet.add_rows(min_rows - current_rows)

# -------------------------------
# HELPERS
# -------------------------------
def clean_name(name):
    return " ".join(name.strip().upper().split())

# -------------------------------
# LOG TO SHEET (FULL FIXED)
# -------------------------------
def log_to_sheet(first_name, last_name, phone, rfid):
    print("\n================ LOGGING START ================")

    if not client:
        print("❌ NO GOOGLE CLIENT")
        return

    try:
        full_name = clean_name(f"{first_name} {last_name}")
        today = datetime.now().strftime("%d-%b")

        spreadsheet = client.open_by_key(SHEET_ID)
        sheet = spreadsheet.get_worksheet(0)

        # 🔥 FIX: ALWAYS ENSURE SIZE BEFORE ANYTHING
        ensure_sheet_size(sheet)

        data = sheet.get_all_values()

        if not data:
            sheet.append_row(["Player Name", today])
            data = sheet.get_all_values()

        header = data[0]

        # -------------------------
        # ADD NEW DAY
        # -------------------------
        if today not in header:
            print("➕ ADDING NEW DAY:", today)

            col = len(header) + 1
            sheet.update_cell(1, col, today)

            # default everyone absent
            for i in range(2, len(data) + 1):
                sheet.update_cell(i, col, "A")

            header.append(today)

        col_index = header.index(today) + 1

        # -------------------------
        # FIND PLAYER
        # -------------------------
        row_index = None
        for i, row in enumerate(data[1:], start=2):
            if row and clean_name(row[0]) == full_name:
                row_index = i
                break

        # -------------------------
        # ADD NEW PLAYER
        # -------------------------
        if not row_index:
            print("➕ ADDING NEW PLAYER:", full_name)

            new_row = [full_name]

            for _ in range(len(header) - 1):
                new_row.append("A")

            sheet.append_row(new_row)
            row_index = len(data) + 1

        # -------------------------
        # MARK PRESENT
        # -------------------------
        print(f"✅ MARKING PRESENT → ROW {row_index}, COL {col_index}")
        sheet.update_cell(row_index, col_index, "P")

    except Exception as e:
        print("❌ SHEET ERROR:", str(e))

    print("================ LOGGING END ================\n")

# -------------------------------
# MODELS
# -------------------------------
class StudentCreate(BaseModel):
    rfid_uid: str
    first_name: str
    last_name: str
    phone: str

class ScanRequest(BaseModel):
    rfid_uid: str

# -------------------------------
# REGISTER
# -------------------------------
@app.post("/register")
def register_student(data: StudentCreate):
    print("📝 REGISTER:", data)

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO students (rfid_uid, first_name, last_name, phone)
            VALUES (%s, %s, %s, %s)
        """, (data.rfid_uid, data.first_name, data.last_name, data.phone))

        conn.commit()

        # add to sheet as ABSENT
        if client:
            full_name = clean_name(f"{data.first_name} {data.last_name}")

            spreadsheet = client.open_by_key(SHEET_ID)
            sheet = spreadsheet.get_worksheet(0)

            ensure_sheet_size(sheet)

            data_sheet = sheet.get_all_values()

            exists = False
            for row in data_sheet[1:]:
                if row and clean_name(row[0]) == full_name:
                    exists = True
                    break

            if not exists:
                new_row = [full_name]

                if data_sheet:
                    for _ in range(len(data_sheet[0]) - 1):
                        new_row.append("A")

                sheet.append_row(new_row)

                print("✅ USER ADDED AS ABSENT")

        return {"success": True}

    except Exception as e:
        return {"success": False, "error": str(e)}

    finally:
        conn.close()

# -------------------------------
# SCAN
# -------------------------------
@app.post("/scan")
def scan_rfid(data: ScanRequest):
    print("\n📡 SCAN HIT:", data.rfid_uid)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT first_name, last_name, phone
        FROM students
        WHERE rfid_uid = %s
    """, (data.rfid_uid,))

    row = cur.fetchone()

    if row:
        first_name, last_name, phone = row

        cur.execute("""
            INSERT INTO attendance (rfid_uid, timestamp)
            VALUES (%s, %s)
        """, (data.rfid_uid, datetime.now().isoformat()))

        conn.commit()
        conn.close()

        log_to_sheet(first_name, last_name, phone, data.rfid_uid)

        return {
            "found": True,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone
        }

    else:
        conn.close()
        return {"found": False}

# -------------------------------
# FRONTEND
# -------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")
