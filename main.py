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
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

    print("✅ GOOGLE SHEETS CONNECTED")

except Exception as e:
    print("❌ GOOGLE ERROR:", str(e))

# -------------------------------
# HELPERS
# -------------------------------
def clean_name(name):
    return " ".join(name.strip().upper().split())

# -------------------------------
# LOG TO SHEET (NEW LOGIC)
# -------------------------------
def log_to_sheet(first_name, last_name):
    print("\n================ LOGGING START ================")

    if not client:
        print("❌ NO GOOGLE CLIENT")
        return

    try:
        full_name = clean_name(f"{first_name} {last_name}")
        today = datetime.now().strftime("%d-%b")

        spreadsheet = client.open_by_key(SHEET_ID)
        sheet = spreadsheet.get_worksheet(0)

        data = sheet.get_all_values()

        if not data:
            print("❌ NO HEADER FOUND")
            return

        header = data[0]

        # ❌ DO NOT CREATE NEW DAY
        if today not in header:
            print(f"⚠️ NOT A BASKETBALL DAY → {today}")
            return

        col_index = header.index(today) + 1

        # -------------------------
        # FIND PLAYER
        # -------------------------
        row_index = None
        for i, row in enumerate(data[1:], start=2):
            if row and clean_name(row[0]) == full_name:
                row_index = i
                break

        # ❌ DO NOT ADD USER AGAIN
        if not row_index:
            print("⚠️ USER NOT IN SHEET (skipping)")
            return

        # -------------------------
        # MARK PRESENT
        # -------------------------
        print(f"✅ CHECK-IN SUCCESS → {full_name}")
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
# REGISTER (NO SHEET WRITE)
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

        print("✅ USER SAVED TO DB ONLY")

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

        # ✅ ALWAYS LOG IN DATABASE
        cur.execute("""
            INSERT INTO attendance (rfid_uid, timestamp)
            VALUES (%s, %s)
        """, (data.rfid_uid, datetime.now().isoformat()))

        conn.commit()
        conn.close()

        print("✅ DATABASE CHECK-IN SUCCESS")

        # ✅ TRY SHEET (optional)
        log_to_sheet(first_name, last_name)

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
