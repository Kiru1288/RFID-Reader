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
# 🔥 MULTI-TAB LOGGING (FIXED)
# -------------------------------
def log_to_sheet(first_name, last_name, phone, rfid):
    print("🚀 log_to_sheet CALLED")

    if not client:
        print("❌ No Google client")
        return

    try:
        full_name = f"{first_name} {last_name}".strip().upper()
        today = datetime.now()

        print(f"📤 LOGGING: {full_name}")

        spreadsheet = client.open("EthioCare Basketball Attendance (1) (1) ")
        SHEETS = ["U11 Attendance", "U16 Attendance"]

        target_sheet = None
        player_row = None

        # FIND PLAYER
        for sheet_name in SHEETS:
            sheet = spreadsheet.worksheet(sheet_name)
            data = sheet.get_all_values()

            for i, row in enumerate(data[1:], start=2):
                if len(row) > 0:
                    name = row[0].strip().upper()

                    # 🔥 STRONG MATCH
                    if full_name == name or full_name.split()[0] in name:
                        target_sheet = sheet
                        player_row = i
                        print(f"✅ Found in {sheet_name} at row {i}")
                        break

            if target_sheet:
                break

        # IF NOT FOUND → ADD
        if not target_sheet:
            print("⚠️ Player NOT FOUND → adding to U11")
            target_sheet = spreadsheet.worksheet("U11 Attendance")
            data = target_sheet.get_all_values()
            header = data[0]

            new_row = [full_name] + [""] * (len(header) - 1)
            target_sheet.append_row(new_row)

            player_row = len(data) + 1

        # GET HEADER
        data = target_sheet.get_all_values()
        header = data[0]

        # FIND TODAY COLUMN
        closest_col = None
        min_diff = 999

        for col in header:
            try:
                col_date = datetime.strptime(col, "%d-%b").replace(year=today.year)
                diff = abs((today - col_date).days)

                if diff < min_diff:
                    min_diff = diff
                    closest_col = col

            except:
                continue

        if not closest_col:
            print("❌ No date column found")
            return

        print(f"📅 Using column: {closest_col}")

        col_index = header.index(closest_col) + 1

        # CHECK EXISTING
        current_value = target_sheet.cell(player_row, col_index).value

        if current_value == "P":
            print("⚠️ Already marked present")
            return

        # UPDATE
        target_sheet.update_cell(player_row, col_index, "P")

        print("✅ MARKED PRESENT IN SHEET")

    except Exception as e:
        print("❌ FINAL ERROR:", e)


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

        # 🔥 ALWAYS LOG (NO COOLDOWN)
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
