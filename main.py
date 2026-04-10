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

# -------------------------------
# STARTUP DEBUG
# -------------------------------
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

# 🔥 YOUR REAL SHEET ID (FINAL FIX)
SHEET_ID = "1-l4fz97lprWxAUcyNr3-pgsLGDIoEJS2TrNWHj7Cj-Q"

try:
    print("\n🌍 Setting up Google Sheets...")

    creds_json = os.getenv("GOOGLE_CREDENTIALS")

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    if creds_json:
        print("✅ FOUND GOOGLE_CREDENTIALS ENV")

        creds_dict = json.loads(creds_json)
        print("🔑 SERVICE ACCOUNT:", creds_dict.get("client_email"))

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

    elif os.path.exists("credentials.json"):
        print("⚠️ USING LOCAL credentials.json")

        with open("credentials.json") as f:
            creds_dict = json.load(f)

        print("🔑 SERVICE ACCOUNT:", creds_dict.get("client_email"))

        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)

    else:
        print("❌ NO GOOGLE CREDENTIALS FOUND")

    print("✅ GOOGLE SHEETS CONNECTED")

except Exception as e:
    print("❌ GOOGLE ERROR:", str(e))

# -------------------------------
# HELPERS
# -------------------------------
def clean_name(name):
    return " ".join(name.strip().upper().split())

# -------------------------------
# TEST ROUTE
# -------------------------------
@app.get("/sheet-test")
def sheet_test():
    try:
        print("🧪 TESTING SHEET ACCESS...")

        spreadsheet = client.open_by_key(SHEET_ID)

        print("✅ ACCESS SUCCESS:", spreadsheet.title)

        return {"status": "success", "title": spreadsheet.title}

    except Exception as e:
        print("❌ ACCESS FAILED:", str(e))
        return {"status": "error", "error": str(e)}

# -------------------------------
# LOG TO SHEET
# -------------------------------
def log_to_sheet(first_name, last_name, phone, rfid):
    print("\n================ LOGGING START ================")

    if not client:
        print("❌ NO GOOGLE CLIENT")
        return

    try:
        full_name = clean_name(f"{first_name} {last_name}")
        today = datetime.now().strftime("%d-%b")

        print("👤 NAME:", full_name)
        print("📅 DATE:", today)

        spreadsheet = client.open_by_key(SHEET_ID)
        print("✅ OPENED:", spreadsheet.title)

        sheet = spreadsheet.get_worksheet(0)

        data = sheet.get_all_values()

        if not data:
            sheet.append_row(["Player Name", today])
            data = sheet.get_all_values()

        header = data[0]

        # FIND PLAYER
        row_index = None
        for i, row in enumerate(data[1:], start=2):
            if row and clean_name(row[0]) == full_name:
                row_index = i
                break

        if not row_index:
            sheet.append_row([full_name])
            row_index = len(data) + 1

        # DATE COLUMN
        if today not in header:
            sheet.update_cell(1, len(header) + 1, today)
            header.append(today)

        col_index = header.index(today) + 1

        print(f"📍 WRITING → ROW {row_index}, COL {col_index}")

        sheet.update_cell(row_index, col_index, "P")

        print("✅ SUCCESS")

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
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO students (rfid_uid, first_name, last_name, phone)
            VALUES (%s, %s, %s, %s)
        """, (data.rfid_uid, data.first_name, data.last_name, data.phone))

        conn.commit()
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
