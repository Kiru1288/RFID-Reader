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
# DATABASE (PostgreSQL)
# -------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)


def init_db():
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


init_db()

# -------------------------------
# GOOGLE SHEETS (PRODUCTION READY)
# -------------------------------
sheet = None

try:
    creds_json = os.getenv("GOOGLE_CREDENTIALS")

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    if creds_json:
        creds_dict = json.loads(creds_json)

        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            creds_dict, scope
        )

        client = gspread.authorize(creds)
        sheet = client.open("Basketball Check-In").sheet1

        print("✅ Google Sheets connected (Render)")

    elif os.path.exists("credentials.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            "credentials.json", scope
        )

        client = gspread.authorize(creds)
        sheet = client.open("Basketball Check-In").sheet1

        print("✅ Google Sheets connected (Local)")

    else:
        print("⚠️ No Google credentials found")

except Exception as e:
    print("❌ Google Sheets error:", e)
    sheet = None


def log_to_sheet(first_name, last_name, phone, rfid):
    if not sheet:
        return

    try:
        now = datetime.now()

        sheet.append_row([
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            f"{first_name} {last_name}",
            phone,
            rfid,
            "Present"
        ])
    except Exception as e:
        print("Google Sheets Error:", e)

# -------------------------------
# COOLDOWN
# -------------------------------
last_scan = {}

def should_log(rfid):
    now = datetime.now()

    if rfid in last_scan:
        diff = (now - last_scan[rfid]).seconds
        if diff < 5:
            return False

    last_scan[rfid] = now
    return True

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

        return {"success": True, "message": "Student registered"}

    except Exception as e:
        return {"success": False, "error": str(e)}

    finally:
        conn.close()

# -------------------------------
# SCAN
# -------------------------------
@app.post("/scan")
def scan_rfid(data: ScanRequest):
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

        if should_log(data.rfid_uid):
            log_to_sheet(first_name, last_name, phone, data.rfid_uid)

        return {
            "found": True,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "message": "Attendance logged"
        }

    else:
        conn.close()
        return {
            "found": False,
            "rfid_uid": data.rfid_uid,
            "message": "New bracelet detected"
        }

# -------------------------------
# GET STUDENTS
# -------------------------------
@app.get("/students")
def get_students():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT rfid_uid, first_name, last_name, phone FROM students")
    rows = cur.fetchall()
    conn.close()

    return [
        {
            "rfid_uid": r[0],
            "first_name": r[1],
            "last_name": r[2],
            "phone": r[3]
        }
        for r in rows
    ]

# -------------------------------
# GET ATTENDANCE
# -------------------------------
@app.get("/attendance")
def get_attendance():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT rfid_uid, timestamp
        FROM attendance
        ORDER BY id DESC
    """)

    rows = cur.fetchall()
    conn.close()

    return [
        {
            "rfid_uid": r[0],
            "timestamp": r[1]
        }
        for r in rows
    ]

# -------------------------------
# SERVE FRONTEND
# -------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")