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
# DATABASE
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
# GOOGLE SHEETS
# -------------------------------
client = None

try:
    creds_json = os.getenv("GOOGLE_CREDENTIALS")

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        print("✅ Google Sheets connected (Render)")

    elif os.path.exists("credentials.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)
        print("✅ Google Sheets connected (Local)")

    else:
        print("❌ No Google credentials found")

except Exception as e:
    print("❌ Google Sheets error:", e)


# -------------------------------
# 🔥 ULTRA DEBUG LOGGING
# -------------------------------
def log_to_sheet(first_name, last_name, phone, rfid):
    print("\n================ DEBUG START ================")
    print("🚀 log_to_sheet CALLED")

    if not client:
        print("❌ No Google client")
        return

    try:
        full_name = f"{first_name} {last_name}".strip().upper()
        today = datetime.now()

        print(f"📤 NAME: {full_name}")
        print(f"📅 TODAY: {today}")

        url = "https://docs.google.com/spreadsheets/d/1tEtYSJnIWKn3uScBhn1e_chiEPLt3jCHF1O9XVvjhnM/edit"
        spreadsheet = client.open_by_url(url)

        print("✅ Spreadsheet opened")

        worksheets = spreadsheet.worksheets()

        print("📄 SHEETS:")
        for ws in worksheets:
            print(" -", ws.title)

        target_sheet = spreadsheet.worksheet("U11 Attendance")

        print(f"📍 USING SHEET: {target_sheet.title}")

        data = target_sheet.get_all_values()

        if not data:
            print("❌ Sheet is empty")
            return

        header = data[0]

        print("📊 HEADER:", header)

        # -------------------------------
        # FIND OR CREATE PLAYER
        # -------------------------------
        player_row = None

        for i, row in enumerate(data[1:], start=2):
            if len(row) > 0 and row[0].strip().upper() == full_name:
                player_row = i
                print(f"✅ Found player at row {i}")
                break

        if not player_row:
            print("⚠️ Adding new player")

            new_row = [full_name] + [""] * (len(header) - 1)
            target_sheet.append_row(new_row)

            player_row = len(data) + 1
            print(f"✅ Added at row {player_row}")

        # -------------------------------
        # FIND TODAY COLUMN
        # -------------------------------
        today_str = today.strftime("%d-%b")
        print("📅 Looking for:", today_str)

        if today_str not in header:
            print("❌ DATE COLUMN NOT FOUND → ADDING")

            target_sheet.update_cell(1, len(header) + 1, today_str)
            header.append(today_str)

        col_index = header.index(today_str) + 1

        print(f"📍 Row: {player_row}, Col: {col_index}")

        # -------------------------------
        # WRITE VALUE
        # -------------------------------
        print("✏️ Writing 'P'...")

        target_sheet.update_cell(player_row, col_index, "P")

        print("✅ SUCCESS")

    except Exception as e:
        print("❌ FINAL ERROR:", str(e))

    print("================ DEBUG END ================\n")


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
    print("📡 SCAN RECEIVED:", data.rfid_uid)

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
        return {
            "found": False,
            "rfid_uid": data.rfid_uid
        }


# -------------------------------
# FRONTEND
# -------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")
