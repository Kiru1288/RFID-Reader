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

try:
    print("\n🌍 Setting up Google Sheets...")

    creds_json = os.getenv("GOOGLE_CREDENTIALS")

    if creds_json:
        print("✅ FOUND GOOGLE_CREDENTIALS ENV")

        creds_dict = json.loads(creds_json)

        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

        print("✅ GOOGLE SHEETS CONNECTED (ENV)")

    elif os.path.exists("credentials.json"):
        print("⚠️ USING LOCAL credentials.json")

        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)

        print("✅ GOOGLE SHEETS CONNECTED (LOCAL)")

    else:
        print("❌ NO GOOGLE CREDENTIALS FOUND")

except Exception as e:
    print("❌ GOOGLE ERROR:", str(e))


# -------------------------------
# NAME CLEANER
# -------------------------------
def clean_name(name):
    return " ".join(name.strip().upper().split())


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

        # ✅ USE YOUR ACTUAL SHEET URL (FIXED)
        SHEET_URL = "https://docs.google.com/spreadsheets/d/1-14fz97lprWxAUcyNr3-pgsLGDIoEJS2TrNWHj7Cj-O/edit"

        print("🌍 OPENING SHEET:", SHEET_URL)

        spreadsheet = client.open_by_url(SHEET_URL)

        print("✅ OPENED SPREADSHEET:", spreadsheet.title)

        # 🔥 DEBUG: LIST ALL TABS
        worksheets = spreadsheet.worksheets()
        print("📄 AVAILABLE TABS:", [ws.title for ws in worksheets])

        # ✅ USE FIRST TAB (Sheet1)
        sheet = spreadsheet.get_worksheet(0)
        print("📄 USING TAB:", sheet.title)

        data = sheet.get_all_values()

        if not data:
            print("⚠️ SHEET EMPTY → CREATING HEADER")
            sheet.append_row(["Player Name", today])
            data = sheet.get_all_values()

        header = data[0]
        print("📊 HEADER:", header)

        # -------------------------
        # FIND PLAYER
        # -------------------------
        row_index = None

        for i, row in enumerate(data[1:], start=2):
            if row and clean_name(row[0]) == full_name:
                row_index = i
                print(f"✅ PLAYER FOUND ROW {i}")
                break

        if not row_index:
            print("➕ ADDING NEW PLAYER:", full_name)
            sheet.append_row([full_name])
            row_index = len(data) + 1

        # -------------------------
        # FIND / CREATE DATE COLUMN
        # -------------------------
        if today not in header:
            print("➕ ADDING NEW DATE COLUMN:", today)
            sheet.update_cell(1, len(header) + 1, today)
            header.append(today)

        col_index = header.index(today) + 1

        print(f"📍 WRITING TO ROW {row_index}, COL {col_index}")

        sheet.update_cell(row_index, col_index, "P")

        print("✅ ATTENDANCE MARKED SUCCESSFULLY")

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
# TEST ROUTE (VERY IMPORTANT)
# -------------------------------
@app.get("/test")
def test():
    print("🧪 TEST ENDPOINT HIT")
    return {"status": "working"}


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

        print("✅ REGISTERED")

        return {"success": True}

    except Exception as e:
        print("❌ REGISTER ERROR:", str(e))
        return {"success": False, "error": str(e)}

    finally:
        conn.close()


# -------------------------------
# SCAN (CRITICAL)
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

        print("✅ USER FOUND:", first_name, last_name)

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
        print("❌ USER NOT FOUND")

        conn.close()
        return {
            "found": False,
            "rfid_uid": data.rfid_uid
        }


# -------------------------------
# FRONTEND
# -------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")
