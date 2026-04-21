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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rfid")

DATABASE_URL = os.getenv("DATABASE_URL")

# 🔥 PRIMARY SHEET (YOUR MAIN ATTENDANCE)
SHEET_ID = "1-l4fz97lprWxAUcyNr3-pgsLGDIoEJS2TrNWHj7Cj-Q"

# 🔥 SECOND TEST SHEET (NEW ONE YOU SENT)
SECOND_SHEET_ID = "11F39-21p5FTjbRSB4ghGM6GO-n8RQnSp_55507B0MAM"

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
    conn.close()

init_db()

# -------------------------------
# GOOGLE SHEETS
# -------------------------------
client = None
try:
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    if creds_json:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            json.loads(creds_json),
            [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive"
            ]
        )
        client = gspread.authorize(creds)
        logger.info("✅ Google Sheets Connected")
except Exception as e:
    logger.error(e)

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
def normalize(name):
    return re.sub(r"\s+", " ", name.strip().lower())

def get_main_sheet():
    return client.open_by_key(SHEET_ID).get_worksheet(0)

def get_second_sheet():
    return client.open_by_key(SECOND_SHEET_ID).get_worksheet(0)

# -------------------------------
# MAIN SHEET LOGIC (UNCHANGED)
# -------------------------------
def get_or_create_today_column(sheet):
    data = sheet.get_all_values()

    if not data:
        return None

    header = data[0]
    today_str = datetime.now().strftime("%d-%b")

    for i in range(1, len(header)):
        if header[i].strip() == today_str:
            return i

    new_col_index = len(header) + 1
    sheet.update_cell(1, new_col_index, today_str)

    logger.info(f"🆕 CREATED NEW COLUMN: {today_str}")

    return new_col_index - 1

def already_checked(first, last):
    try:
        sheet = get_main_sheet()
        col = get_or_create_today_column(sheet)

        data = sheet.get_all_values()
        target = normalize(f"{first} {last}")

        for row in data[1:]:
            if normalize(row[0]) == target:
                return len(row) > col and row[col] == "P"

        return False

    except Exception as e:
        logger.error(e)
        return False

def write_main_sheet(first, last):
    try:
        sheet = get_main_sheet()
        col_index = get_or_create_today_column(sheet)
        col = col_index + 1

        data = sheet.get_all_values()
        target = normalize(f"{first} {last}")

        for i, row in enumerate(data[1:], start=2):
            if normalize(row[0]) == target:
                sheet.update_cell(i, col, "P")
                return True

        header_len = len(data[0])
        new_row = [f"{first} {last}"] + [""] * (header_len - 1)
        new_row[col - 1] = "P"

        sheet.append_row(new_row)
        return True

    except Exception as e:
        logger.error(e)
        return False

# -------------------------------
# 🔥 SECOND SHEET WRITE (NEW)
# -------------------------------
def write_second_sheet(first, last):
    try:
        sheet = get_second_sheet()

        name = f"{first} {last}"
        date = datetime.now().strftime("%Y-%m-%d")

        # ALWAYS APPEND (NO DUP CHECK)
        sheet.append_row([name, date])

        logger.info(f"🧪 SECOND SHEET LOGGED: {name} | {date}")
        return True

    except Exception as e:
        logger.error(f"❌ SECOND SHEET ERROR: {e}")
        return False

# -------------------------------
# CORE
# -------------------------------
def process(rfid):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cur.execute("SELECT * FROM students WHERE rfid_uid=%s", (rfid,))
        student = cur.fetchone()

        if not student:
            return {"status": "not_found"}

        first = student["first_name"]
        last = student["last_name"]

        if already_checked(first, last):
            return {
                "status": "already_checked",
                "first_name": first,
                "last_name": last
            }

        # MAIN SHEET
        if not write_main_sheet(first, last):
            return {"status": "sheet_error"}

        # 🔥 SECOND SHEET (ALWAYS WRITE)
        write_second_sheet(first, last)

        # DATABASE LOG
        cur.execute("INSERT INTO attendance (rfid_uid) VALUES (%s)", (rfid,))
        conn.commit()

        return {
            "status": "success",
            "first_name": first,
            "last_name": last
        }

    except Exception as e:
        logger.error(e)
        return {"status": "error"}

    finally:
        conn.close()

# -------------------------------
# ROUTES
# -------------------------------
@app.post("/scan")
def scan(data: ScanRequest):
    return process(data.rfid_uid)

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

app.mount("/", StaticFiles(directory="static", html=True), name="static")
