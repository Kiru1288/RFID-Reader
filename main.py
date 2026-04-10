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
TEST_MODE = True

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

    # -------------------------
    # STUDENTS TABLE
    # -------------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id SERIAL PRIMARY KEY,
        rfid_uid TEXT UNIQUE NOT NULL,
        first_name TEXT,
        last_name TEXT,
        phone TEXT
    )
    """)

    # -------------------------
    # ATTENDANCE TABLE (FIXED)
    # -------------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id SERIAL PRIMARY KEY,
        rfid_uid TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        date TEXT NOT NULL
    )
    """)

    # -------------------------
    # SAFE UNIQUE INDEX
    # -------------------------
    cur.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS unique_daily_scan
    ON attendance (rfid_uid, date)
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("✅ DB READY")

init_db()

# -------------------------------
# GOOGLE SHEETS
# -------------------------------
client = None

try:
    logger.info("🌍 Setting up Google Sheets...")

    creds_json = os.getenv("GOOGLE_CREDENTIALS")

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        logger.info("✅ GOOGLE SHEETS CONNECTED")
    else:
        logger.warning("⚠️ GOOGLE_CREDENTIALS not found. Sheets logging disabled.")

except Exception as e:
    client = None
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
def clean_name(name: str) -> str:
    return " ".join(name.strip().upper().split())

def valid_rfid(rfid: str) -> bool:
    rfid = rfid.strip()
    return bool(re.fullmatch(r"\d{6,30}", rfid))

def today_label() -> str:
    return datetime.now().strftime("%d-%b")

def get_sheet():
    if not client:
        return None
    spreadsheet = client.open_by_key(SHEET_ID)
    return spreadsheet.get_worksheet(0)

def log_to_sheet(first_name: str, last_name: str) -> dict:
    logger.info("================ LOGGING START ================")

    if not client:
        logger.warning("⚠️ NO GOOGLE CLIENT")
        logger.info("================ LOGGING END ================")
        return {
            "sheet_logged": False,
            "sheet_reason": "google_unavailable"
        }

    try:
        full_name = clean_name(f"{first_name} {last_name}")
        today = today_label()

        sheet = get_sheet()
        if sheet is None:
            logger.warning("⚠️ SHEET NOT AVAILABLE")
            logger.info("================ LOGGING END ================")
            return {
                "sheet_logged": False,
                "sheet_reason": "sheet_unavailable"
            }

        data = sheet.get_all_values()

        if not data:
            logger.warning("⚠️ NO HEADER FOUND")
            logger.info("================ LOGGING END ================")
            return {
                "sheet_logged": False,
                "sheet_reason": "no_header"
            }

        header = data[0]

        if today not in header:
            logger.info(f"⚠️ NOT A BASKETBALL DAY → {today}")
            logger.info("================ LOGGING END ================")
            return {
                "sheet_logged": False,
                "sheet_reason": "not_basketball_day"
            }

        col_index = header.index(today) + 1

        row_index = None
        for i, row in enumerate(data[1:], start=2):
            if row and len(row) > 0 and clean_name(row[0]) == full_name:
                row_index = i
                break

        if not row_index:
            logger.info("⚠️ USER NOT IN SHEET (skipping)")
            logger.info("================ LOGGING END ================")
            return {
                "sheet_logged": False,
                "sheet_reason": "user_not_in_sheet"
            }

        logger.info(f"✅ SHEET CHECK-IN SUCCESS → {full_name}")
        sheet.update_cell(row_index, col_index, "P")

        logger.info("================ LOGGING END ================")
        return {
            "sheet_logged": True,
            "sheet_reason": "logged"
        }

    except Exception as e:
        logger.error(f"❌ SHEET ERROR: {str(e)}")
        logger.info("================ LOGGING END ================")
        return {
            "sheet_logged": False,
            "sheet_reason": f"sheet_error: {str(e)}"
        }

def process_check_in(rfid_uid: str) -> dict:
    logger.info(f"📡 SCAN HIT: {rfid_uid}")

    if not valid_rfid(rfid_uid):
        logger.warning(f"❌ INVALID RFID FORMAT: {rfid_uid}")
        return {
            "status": "invalid_rfid",
            "message": "Invalid RFID format",
            "found": False
        }

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cur.execute("""
            SELECT first_name, last_name, phone
            FROM students
            WHERE rfid_uid = %s
        """, (rfid_uid,))
        student = cur.fetchone()

        if not student:
            logger.warning("⚠️ RFID NOT REGISTERED")
            return {
                "status": "not_found",
                "message": "RFID not registered",
                "found": False
            }

        first_name = student["first_name"]
        last_name = student["last_name"]
        phone = student["phone"]

        # Duplicate daily scan protection
        cur.execute("""
            SELECT 1
            FROM attendance
            WHERE rfid_uid = %s
              AND DATE(timestamp) = CURRENT_DATE
            LIMIT 1
        """, (rfid_uid,))
        already_checked = cur.fetchone()

        if already_checked:
            logger.info(f"⚠️ ALREADY CHECKED IN TODAY → {first_name} {last_name}")

            # Optional sheet status still checked, but no DB insert again
            sheet_result = log_to_sheet(first_name, last_name)

            return {
                "status": "already_checked_in",
                "message": "Already checked in today",
                "found": True,
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone,
                "sheet_logged": sheet_result["sheet_logged"],
                "sheet_reason": sheet_result["sheet_reason"]
            }

        # Save attendance in DB first
        now = datetime.now()
        cur.execute("""
            INSERT INTO attendance (rfid_uid, timestamp)
            VALUES (%s, %s)
        """, (rfid_uid, now))
        conn.commit()

        logger.info(f"✅ DATABASE CHECK-IN SUCCESS → {first_name} {last_name}")

        # Try sheet logging, but do not fail check-in if sheet fails
        sheet_result = log_to_sheet(first_name, last_name)

        if TEST_MODE:
            logger.info(
                f"🧪 TEST LOG | user={first_name} {last_name} | "
                f"db_checkin=success | sheet_logged={sheet_result['sheet_logged']} | "
                f"sheet_reason={sheet_result['sheet_reason']}"
            )

        return {
            "status": "success",
            "message": "Checked in successfully",
            "found": True,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "sheet_logged": sheet_result["sheet_logged"],
            "sheet_reason": sheet_result["sheet_reason"]
        }

    except psycopg2.Error as e:
        logger.error(f"❌ DATABASE ERROR: {str(e)}")
        return {
            "status": "db_error",
            "message": str(e),
            "found": False
        }

    finally:
        conn.close()

# -------------------------------
# ROUTES
# -------------------------------
@app.get("/health")
def health_check():
    db_ok = False
    sheets_ok = False
    sheet_title = None

    try:
        conn = get_db()
        conn.close()
        db_ok = True
    except Exception as e:
        logger.error(f"❌ HEALTH DB ERROR: {str(e)}")

    try:
        if client:
            spreadsheet = client.open_by_key(SHEET_ID)
            sheet_title = spreadsheet.title
            sheets_ok = True
    except Exception as e:
        logger.error(f"❌ HEALTH SHEETS ERROR: {str(e)}")

    return {
        "status": "ok",
        "database": db_ok,
        "google_sheets": sheets_ok,
        "sheet_title": sheet_title
    }

@app.post("/register")
def register_student(data: StudentCreate):
    logger.info(f"📝 REGISTER REQUEST: {data.dict()}")

    rfid_uid = data.rfid_uid.strip()
    first_name = data.first_name.strip()
    last_name = data.last_name.strip()
    phone = data.phone.strip()

    if not valid_rfid(rfid_uid):
        return {
            "success": False,
            "status": "invalid_rfid",
            "message": "Invalid RFID format"
        }

    if not first_name or not last_name:
        return {
            "success": False,
            "status": "invalid_name",
            "message": "First and last name are required"
        }

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT 1 FROM students WHERE rfid_uid = %s
        """, (rfid_uid,))
        existing = cur.fetchone()

        if existing:
            logger.warning(f"⚠️ RFID ALREADY REGISTERED: {rfid_uid}")
            return {
                "success": False,
                "status": "already_registered",
                "message": "RFID already registered"
            }

        cur.execute("""
            INSERT INTO students (rfid_uid, first_name, last_name, phone)
            VALUES (%s, %s, %s, %s)
        """, (rfid_uid, first_name, last_name, phone))

        conn.commit()

        logger.info(f"✅ USER SAVED TO DB ONLY → {first_name} {last_name}")

        return {
            "success": True,
            "status": "registered",
            "message": "User registered successfully"
        }

    except Exception as e:
        logger.error(f"❌ REGISTER ERROR: {str(e)}")
        return {
            "success": False,
            "status": "error",
            "message": str(e)
        }

    finally:
        conn.close()

@app.post("/scan")
def scan_rfid(data: ScanRequest):
    return process_check_in(data.rfid_uid.strip())

@app.get("/student/{rfid_uid}")
def get_student(rfid_uid: str):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cur.execute("""
            SELECT id, rfid_uid, first_name, last_name, phone
            FROM students
            WHERE rfid_uid = %s
        """, (rfid_uid,))
        student = cur.fetchone()

        if not student:
            return {
                "found": False,
                "message": "Student not found"
            }

        return {
            "found": True,
            "student": student
        }

    except Exception as e:
        logger.error(f"❌ GET STUDENT ERROR: {str(e)}")
        return {
            "found": False,
            "message": str(e)
        }

    finally:
        conn.close()

@app.get("/stats/{rfid_uid}")
def get_attendance_stats(rfid_uid: str):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cur.execute("""
            SELECT first_name, last_name, phone
            FROM students
            WHERE rfid_uid = %s
        """, (rfid_uid,))
        student = cur.fetchone()

        if not student:
            return {
                "found": False,
                "message": "Student not found"
            }

        cur.execute("""
            SELECT COUNT(*) AS total_checkins
            FROM attendance
            WHERE rfid_uid = %s
        """, (rfid_uid,))
        total_checkins = cur.fetchone()["total_checkins"]

        # Basketball days = number of day columns in sheet minus name column
        basketball_days = None
        attendance_percentage = None

        try:
            if client:
                sheet = get_sheet()
                if sheet:
                    data = sheet.get_all_values()
                    if data and len(data[0]) > 1:
                        basketball_days = len(data[0]) - 1
                        if basketball_days > 0:
                            attendance_percentage = round((total_checkins / basketball_days) * 100, 2)
        except Exception as e:
            logger.warning(f"⚠️ STATS SHEET ERROR: {str(e)}")

        return {
            "found": True,
            "first_name": student["first_name"],
            "last_name": student["last_name"],
            "phone": student["phone"],
            "total_checkins": total_checkins,
            "basketball_days": basketball_days,
            "attendance_percentage": attendance_percentage
        }

    except Exception as e:
        logger.error(f"❌ STATS ERROR: {str(e)}")
        return {
            "found": False,
            "message": str(e)
        }

    finally:
        conn.close()

@app.get("/sheet-test")
def sheet_test():
    try:
        if not client:
            return {
                "status": "error",
                "error": "Google Sheets client not connected"
            }

        spreadsheet = client.open_by_key(SHEET_ID)
        return {
            "status": "success",
            "title": spreadsheet.title
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

# -------------------------------
# FRONTEND
# -------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")
