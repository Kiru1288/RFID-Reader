from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
from datetime import datetime
from pydantic import BaseModel

# ✅ NEW IMPORTS (Google Sheets)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI()

# -------------------------------
# CORS (allow frontend to connect)
# -------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "students.db"

# -------------------------------
# GOOGLE SHEETS SETUP
# -------------------------------
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    "credentials.json", scope
)

client = gspread.authorize(creds)

# ⚠️ MAKE SURE THIS NAME MATCHES YOUR SHEET
sheet = client.open("Basketball Check-In").sheet1


def log_to_sheet(first_name, last_name, phone, rfid):
    now = datetime.now()

    sheet.append_row([
        now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M:%S"),
        f"{first_name} {last_name}",
        phone,
        rfid,
        "Present"
    ])


# -------------------------------
# DUPLICATE SCAN PROTECTION
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
# DATABASE SETUP
# -------------------------------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rfid_uid TEXT UNIQUE,
        first_name TEXT,
        last_name TEXT,
        phone TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rfid_uid TEXT,
        timestamp TEXT
    )
    """)

    conn.commit()
    conn.close()

init_db()


# -------------------------------
# DB HELPER
# -------------------------------
def get_db():
    return sqlite3.connect(DB_NAME)


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
# ROOT TEST
# -------------------------------
@app.get("/")
def root():
    return {"message": "RFID Attendance API Running"}


# -------------------------------
# REGISTER STUDENT
# -------------------------------
@app.post("/register")
def register_student(data: StudentCreate):
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO students (rfid_uid, first_name, last_name, phone)
            VALUES (?, ?, ?, ?)
        """, (data.rfid_uid, data.first_name, data.last_name, data.phone))

        conn.commit()

        return {
            "success": True,
            "message": "Student registered successfully"
        }

    except sqlite3.IntegrityError:
        return {
            "success": False,
            "error": "RFID already registered"
        }

    finally:
        conn.close()


# -------------------------------
# SCAN RFID
# -------------------------------
@app.post("/scan")
def scan_rfid(data: ScanRequest):
    conn = get_db()
    cur = conn.cursor()

    # Check if student exists
    cur.execute("""
        SELECT first_name, last_name, phone
        FROM students
        WHERE rfid_uid = ?
    """, (data.rfid_uid,))

    row = cur.fetchone()

    if row:
        first_name, last_name, phone = row

        # ✅ Log to DATABASE
        cur.execute("""
            INSERT INTO attendance (rfid_uid, timestamp)
            VALUES (?, ?)
        """, (data.rfid_uid, datetime.now().isoformat()))

        conn.commit()
        conn.close()

        # ✅ Log to GOOGLE SHEET (with duplicate protection)
        if should_log(data.rfid_uid):
            try:
                log_to_sheet(first_name, last_name, phone, data.rfid_uid)
            except Exception as e:
                print("Google Sheets Error:", e)

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
# GET ALL STUDENTS
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
# GET ATTENDANCE LOG
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