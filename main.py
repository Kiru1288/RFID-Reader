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
# GOOGLE SHEETS SETUP
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
# NAME CLEANER (CRITICAL)
# -------------------------------
def clean_name(name):
    return " ".join(name.strip().upper().split())


# -------------------------------
# LOG TO GOOGLE SHEET (FINAL)
# -------------------------------
def log_to_sheet(first_name, last_name, phone, rfid):
    print("\n================ DEBUG START ================")
    print("🚀 log_to_sheet CALLED")

    if not client:
        print("❌ No Google client")
        return

    try:
        full_name = clean_name(f"{first_name} {last_name}")
        today = datetime.now()

        print(f"📤 CLEANED NAME: '{full_name}'")
        print(f"📅 TODAY: {today}")

        # 🔥 YOUR WORKING SHEET URL
        url = "https://docs.google.com/spreadsheets/d/1tEtYSJnIWKn3uScBhn1e_chiEPLt3jCHF1O9XVvjhnM/edit"
        spreadsheet = client.open_by_url(url)

        print("✅ Spreadsheet opened")

        # 🔥 FORCE CORRECT TAB
        target_sheet = spreadsheet.worksheet("Sheet1")

        print(f"📍 USING SHEET: '{target_sheet.title}'")

        data = target_sheet.get_all_values()

        if not data or len(data) < 1:
            print("❌ Sheet empty or invalid")
            return

        header = [h.strip() for h in data[0]]

        print("📊 HEADER:", header)

        # -------------------------------
        # FIND PLAYER
        # -------------------------------
        player_row = None

        print("\n📋 CHECKING PLAYERS:")
        for i, row in enumerate(data[1:], start=2):
            if len(row) > 0:
                sheet_name = clean_name(row[0])

                print(f"🔍 Comparing '{sheet_name}' vs '{full_name}'")

                if sheet_name == full_name:
                    player_row = i
                    print(f"✅ Found player at row {i}")
                    break

        # -------------------------------
        # ADD PLAYER IF NOT FOUND
        # -------------------------------
        if not player_row:
            print("⚠️ Player not found → ADDING")

            new_row = [full_name] + [""] * (len(header) - 1)
            target_sheet.append_row(new_row)

            player_row = len(data) + 1
            print(f"✅ Added at row {player_row}")

        # -------------------------------
        # FIND TODAY COLUMN
        # -------------------------------
        today_str = today.strftime("%d-%b")
        print("📅 Looking for column:", today_str)

        if today_str not in header:
            print("➕ Adding new date column")

            target_sheet.update_cell(1, len(header) + 1, today_str)
            header.append(today_str)

        col_index = header.index(today_str) + 1

        print(f"📍 FINAL POSITION → Row: {player_row}, Col: {col_index}")

        # -------------------------------
        # WRITE ATTENDANCE
        # -------------------------------
        print("✏️ Writing 'P'...")

        target_sheet.update_cell(player_row, col_index, "P")

        print("✅ SUCCESS — ATTENDANCE MARKED")

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
