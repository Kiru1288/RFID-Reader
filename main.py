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
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
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
def valid_rfid(rfid: str):
    return bool(re.fullmatch(r"\d{6,30}", rfid.strip()))

def today_label():
    return datetime.now().strftime("%d-%b")

def get_sheet():
    if not client:
        return None
    return client.open_by_key(SHEET_ID).get_worksheet(0)

def normalize_name(name):
    return re.sub(r"\s+", " ", name.strip().lower())

# -------------------------------
# CHECK IF ALREADY PRESENT
# -------------------------------
def check_already_in_sheet(first_name, last_name):
    try:
        sheet = get_sheet()
        data = sheet.get_all_values()

        if not data:
            return False

        header = data[0]
        today = today_label()

        if today not in header:
            logger.error("❌ DATE COLUMN NOT FOUND")
            return False

        col = header.index(today)
        target = normalize_name(f"{first_name} {last_name}")

        for row in data[1:]:
            if not row:
                continue

            sheet_name = normalize_name(row[0])

            if sheet_name == target:
                return len(row) > col and row[col] == "P"

        return False

    except Exception as e:
        logger.error(f"❌ CHECK ERROR: {str(e)}")
        return False

# -------------------------------
# WRITE TO SHEET (FIXED)
# -------------------------------
def write_to_sheet(first_name, last_name):
    try:
        sheet = get_sheet()
        data = sheet.get_all_values()

        if not data:
            logger.error("❌ EMPTY SHEET")
            return False

        header = data[0]
        today = today_label()

        if today not in header:
            logger.error(f"❌ DATE '{today}' NOT FOUND")
            return False

        col = header.index(today) + 1
        target = normalize_name(f"{first_name} {last_name}")

        logger.info(f"🔍 LOOKING FOR: {target}")

        for i, row in enumerate(data[1:], start=2):
            if not row:
                continue

            sheet_name = normalize_name(row[0])

            logger.info(f"➡️ Comparing with: {sheet_name}")

            if sheet_name == target:
                sheet.update_cell(i, col, "P")
                logger.info(f"✅ UPDATED row={i}, col={col}")
                return True

        # 🔥 AUTO ADD IF NOT FOUND
        logger.warning("⚠️ NAME NOT FOUND → ADDING TO SHEET")

        new_row = [f"{first_name} {last_name}"]
        for _ in range(len(header) - 1):
            new_row.append("")

        new_row[col - 1] = "P"

        sheet.append_row(new_row)
        logger.info("✅ NEW ROW ADDED")

        return True

    except Exception as e:
        logger.error(f"❌ SHEET ERROR: {str(e)}")
        return False

# -------------------------------
# CORE LOGIC
# -------------------------------
def process_check_in(rfid_uid: str):
    logger.info(f"📡 SCAN: {rfid_uid}")

    if not valid_rfid(rfid_uid):
        return {"status": "invalid"}

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cur.execute("SELECT * FROM students WHERE rfid_uid=%s", (rfid_uid,))
        student = cur.fetchone()

        if not student:
            logger.error("❌ STUDENT NOT FOUND IN DB")
            return {"status": "not_found"}

        already = check_already_in_sheet(student["first_name"], student["last_name"])

        if already:
            return {"status": "already_checked"}

        success = write_to_sheet(student["first_name"], student["last_name"])

        if not success:
            return {"status": "sheet_failed"}

        cur.execute("""
        INSERT INTO attendance (rfid_uid, timestamp)
        VALUES (%s, %s)
        """, (rfid_uid, datetime.now()))

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
@app.post("/scan")
def scan(data: ScanRequest):
    return process_check_in(data.rfid_uid)

@app.post("/register")
def register(data: StudentCreate):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO students (rfid_uid, first_name, last_name, phone)
    VALUES (%s, %s, %s, %s)
    """, (data.rfid_uid, data.first_name, data.last_name, data.phone))

    conn.commit()
    conn.close()

    return {"success": True}

@app.get("/health")
def health():
    return {"status": "ok"}

# -------------------------------
# FRONTEND
# -------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")
