from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime
import psycopg2
import psycopg2.extras
import os
import json
import re
import logging
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI()

# -------------------------------
# LOGGING
# -------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("rfid_attendance")
logger.info("🔥🔥🔥 SERVER STARTED 🔥🔥🔥")

# -------------------------------
# CONFIG
# -------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
SHEET_ID = "1-l4fz97lprWxAUcyNr3-pgsLGDIoEJS2TrNWHj7Cj-Q"

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
def get_db():
    logger.info("📡 Connecting to DB...")
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id SERIAL PRIMARY KEY,
        rfid_uid TEXT UNIQUE NOT NULL,
        first_name TEXT,
        last_name TEXT,
        phone TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id SERIAL PRIMARY KEY,
        rfid_uid TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        date TEXT
    )
    """)

    cur.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS unique_daily_scan
    ON attendance (rfid_uid, date)
    """)

    conn.commit()
    cur.close()
    conn.close()

    logger.info("✅ DB READY")

init_db()

# -------------------------------
# GOOGLE SHEETS
# -------------------------------
client = None

try:
    logger.info("🌍 Setting up Google Sheets...")

    creds_json = os.getenv("GOOGLE_CREDENTIALS")

    if creds_json:
        creds_dict = json.loads(creds_json)
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        logger.info("✅ GOOGLE SHEETS CONNECTED")
    else:
        logger.warning("⚠️ GOOGLE_CREDENTIALS missing")

except Exception as e:
    logger.error(f"❌ GOOGLE ERROR: {str(e)}")

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
# HELPERS
# -------------------------------
def valid_rfid(rfid: str) -> bool:
    return bool(re.fullmatch(r"\d{6,30}", rfid.strip()))

def today_label():
    return datetime.now().strftime("%d-%b")

def get_sheet():
    if not client:
        return None
    return client.open_by_key(SHEET_ID).get_worksheet(0)

# 🔥 CRITICAL FIX: RETURN TRUE/FALSE
def log_to_sheet(first_name, last_name):
    try:
        if not client:
            logger.error("❌ NO SHEET CLIENT")
            return False

        sheet = get_sheet()
        if not sheet:
            logger.error("❌ NO SHEET FOUND")
            return False

        data = sheet.get_all_values()
        header = data[0]
        today = today_label()

        logger.info(f"📅 TODAY: {today}")
        logger.info(f"📊 HEADERS: {header}")

        if today not in header:
            logger.error("❌ DATE COLUMN NOT FOUND")
            return False

        col = header.index(today) + 1
        full_name = f"{first_name} {last_name}".strip().upper()

        for i, row in enumerate(data[1:], start=2):
            if row and row[0].strip().upper() == full_name:
                sheet.update_cell(i, col, "P")
                logger.info(f"✅ SHEET UPDATED row={i}, col={col}")
                return True

        logger.error("❌ NAME NOT FOUND IN SHEET")
        return False

    except Exception as e:
        logger.error(f"❌ SHEET ERROR: {str(e)}")
        return False

# -------------------------------
# CORE LOGIC (FIXED)
# -------------------------------
def process_check_in(rfid_uid: str):
    logger.info(f"📡 SCAN HIT: {rfid_uid}")

    if not valid_rfid(rfid_uid):
        return {"status": "invalid"}

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cur.execute("SELECT * FROM students WHERE rfid_uid=%s", (rfid_uid,))
        student = cur.fetchone()

        if not student:
            return {"status": "not_found"}

        today = datetime.now().date().isoformat()

        # CHECK DB FIRST
        cur.execute("""
        SELECT 1 FROM attendance
        WHERE rfid_uid=%s AND date=%s
        """, (rfid_uid, today))

        if cur.fetchone():
            return {"status": "already_checked"}

        # 🔥 FIX: UPDATE SHEET FIRST
        sheet_success = log_to_sheet(student["first_name"], student["last_name"])

        if not sheet_success:
            logger.error("❌ BLOCKED: SHEET FAILED → NOT SAVING TO DB")
            return {"status": "sheet_failed"}

        # ONLY SAVE IF SHEET WORKED
        cur.execute("""
        INSERT INTO attendance (rfid_uid, timestamp, date)
        VALUES (%s, %s, %s)
        """, (rfid_uid, datetime.now(), today))

        conn.commit()

        return {
            "status": "success",
            "first_name": student["first_name"],
            "last_name": student["last_name"]
        }

    except Exception as e:
        logger.error(f"❌ ERROR: {str(e)}")
        return {"status": "error"}

    finally:
        conn.close()

# -------------------------------
# ROUTES
# -------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/register")
def register(data: StudentCreate):
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

@app.post("/scan")
def scan(data: ScanRequest):
    return process_check_in(data.rfid_uid)

# -------------------------------
# FRONTEND
# -------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")
