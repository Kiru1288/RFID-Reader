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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rfid")

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
            ["https://spreadsheets.google.com/feeds",
             "https://www.googleapis.com/auth/drive"]
        )
        client = gspread.authorize(creds)
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
def get_sheet():
    return client.open_by_key(SHEET_ID).get_worksheet(0)

def normalize(name):
    return re.sub(r"\s+", " ", name.strip().lower())

# 🔥 NEW: EXACT TODAY COLUMN ONLY
def get_today_column(header):
    today_str = datetime.now().strftime("%d-%b")

    for i in range(1, len(header)):  # skip column A
        if header[i].strip() == today_str:
            return i

    return None

# -------------------------------
# CHECK
# -------------------------------
def already_checked(first, last):
    sheet = get_sheet()
    data = sheet.get_all_values()

    header = data[0]
    col = get_today_column(header)

    if col is None:
        logger.error("❌ TODAY COLUMN NOT FOUND")
        return False

    target = normalize(f"{first} {last}")

    for row in data[1:]:
        if normalize(row[0]) == target:
            return len(row) > col and row[col] == "P"

    return False

# -------------------------------
# WRITE
# -------------------------------
def write_sheet(first, last):
    sheet = get_sheet()
    data = sheet.get_all_values()

    header = data[0]
    col_index = get_today_column(header)

    if col_index is None:
        logger.error("❌ TODAY COLUMN NOT FOUND")
        return False

    col = col_index + 1
    target = normalize(f"{first} {last}")

    for i, row in enumerate(data[1:], start=2):
        if normalize(row[0]) == target:
            sheet.update_cell(i, col, "P")
            return True

    # add new student
    new_row = [f"{first} {last}"] + [""] * (len(header) - 1)
    new_row[col - 1] = "P"
    sheet.append_row(new_row)

    return True

# -------------------------------
# CORE
# -------------------------------
def process(rfid):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT * FROM students WHERE rfid_uid=%s", (rfid,))
    student = cur.fetchone()

    if not student:
        return {"status": "not_found"}

    if already_checked(student["first_name"], student["last_name"]):
        return {"status": "already_checked"}

    if not write_sheet(student["first_name"], student["last_name"]):
        return {"status": "sheet_error"}

    cur.execute("INSERT INTO attendance (rfid_uid) VALUES (%s)", (rfid,))
    conn.commit()
    conn.close()

    return {"status": "success"}

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
