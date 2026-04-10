// -----------------------------
// CONFIG
// -----------------------------
const API_URL = "https://rfid-reader-hrip.onrender.com";

// -----------------------------
// ELEMENTS
// -----------------------------
const scanInput = document.getElementById("scanInput");
const resultBox = document.getElementById("result");
const nameEl = document.getElementById("name");
const phoneEl = document.getElementById("phone");
const statusEl = document.getElementById("status");

const formBox = document.getElementById("registerForm");
const firstInput = document.getElementById("firstName");
const lastInput = document.getElementById("lastName");
const phoneInput = document.getElementById("phoneInput");
const saveBtn = document.getElementById("saveBtn");

// -----------------------------
// STATE
// -----------------------------
let currentRFID = null;
let scanTimeout = null;
let lastScannedRFID = null;
let lastScanAt = 0;
const SCAN_COOLDOWN_MS = 2000;

// -----------------------------
// FOCUS CONTROL
// -----------------------------
function focusInput() {
  if (formBox.style.display !== "block") {
    scanInput.focus();
  }
}

document.addEventListener("click", (e) => {
  const isInsideForm = e.target.closest("#registerForm");
  if (!isInsideForm) {
    focusInput();
  }
});

saveBtn.addEventListener("mousedown", (e) => {
  e.stopPropagation();
});

setInterval(() => {
  focusInput();
}, 1000);

// -----------------------------
// RESET UI
// -----------------------------
function resetUI() {
  resultBox.style.background = "#1f2937";
  nameEl.innerText = "Scan RFID Bracelet";
  phoneEl.innerText = "";
  statusEl.innerText = "";
  hideForm();
  scanInput.value = "";
  focusInput();
}

function flashReset(delay = 3000) {
  setTimeout(() => {
    resetUI();
  }, delay);
}

// -----------------------------
// UI STATES
// -----------------------------
function showState({ bg, title, phone = "", status = "", reset = true, delay = 3000 }) {
  resultBox.style.background = bg;
  nameEl.innerText = title;
  phoneEl.innerText = phone;
  statusEl.innerText = status;

  if (reset) {
    flashReset(delay);
  }
}

function showSuccess(data) {
  let extraStatus = "✅ Checked In";

  if (data.sheet_logged === false && data.sheet_reason === "not_basketball_day") {
    extraStatus = "✅ Checked In (Not basketball day on sheet)";
  } else if (data.sheet_logged === false && data.sheet_reason === "user_not_in_sheet") {
    extraStatus = "✅ Checked In (User not on sheet)";
  } else if (data.sheet_logged === true) {
    extraStatus = "✅ Checked In + Sheet Updated";
  }

  showState({
    bg: "#16a34a",
    title: `${data.first_name} ${data.last_name}`,
    phone: data.phone ? `📞 ${data.phone}` : "",
    status: extraStatus
  });
}

function showAlreadyCheckedIn(data) {
  let extraStatus = "⚠️ Already checked in today";

  if (data.sheet_logged === false && data.sheet_reason === "not_basketball_day") {
    extraStatus = "⚠️ Already checked in today (Not basketball day on sheet)";
  }

  showState({
    bg: "#d97706",
    title: `${data.first_name} ${data.last_name}`,
    phone: data.phone ? `📞 ${data.phone}` : "",
    status: extraStatus
  });
}

function showError(message) {
  showState({
    bg: "#dc2626",
    title: "Error",
    phone: "",
    status: `❌ ${message}`
  });
}

function showWarning(message) {
  showState({
    bg: "#d97706",
    title: "Warning",
    phone: "",
    status: `⚠️ ${message}`
  });
}

function showRegisterForm(rfid) {
  currentRFID = rfid;

  resultBox.style.background = "#2563eb";
  nameEl.innerText = "New Bracelet Detected";
  phoneEl.innerText = "";
  statusEl.innerText = "Enter student info below";

  formBox.style.display = "block";

  firstInput.value = "";
  lastInput.value = "";
  phoneInput.value = "";

  firstInput.focus();
}

function hideForm() {
  formBox.style.display = "none";
}

// -----------------------------
// SCAN INPUT HANDLER
// -----------------------------
scanInput.addEventListener("input", (e) => {
  const value = e.target.value;

  clearTimeout(scanTimeout);

  scanTimeout = setTimeout(() => {
    const trimmed = value.trim();

    if (trimmed.length > 0) {
      handleScan(trimmed);
      scanInput.value = "";
    }
  }, 100);
});

// -----------------------------
// SCAN LOGIC
// -----------------------------
async function handleScan(rfid) {
  const now = Date.now();

  if (rfid === lastScannedRFID && now - lastScanAt < SCAN_COOLDOWN_MS) {
    console.log("⏱️ Duplicate scan blocked:", rfid);
    return;
  }

  lastScannedRFID = rfid;
  lastScanAt = now;
  currentRFID = rfid;

  console.log("📡 SCANNED VALUE:", rfid);
  console.log("🚀 Sending scan to backend:", `${API_URL}/scan`);

  try {
    const res = await fetch(`${API_URL}/scan`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ rfid_uid: rfid })
    });

    const data = await res.json();

    console.log("📥 SCAN RESPONSE:", data);

    if (!res.ok) {
      showError(data.message || "Scan failed");
      return;
    }

    switch (data.status) {
      case "success":
        hideForm();
        showSuccess(data);
        break;

      case "already_checked_in":
        hideForm();
        showAlreadyCheckedIn(data);
        break;

      case "not_found":
        showRegisterForm(rfid);
        break;

      case "invalid_rfid":
        hideForm();
        showError("Invalid RFID");
        break;

      case "db_error":
        hideForm();
        showError("Database Error");
        break;

      default:
        if (data.found === false) {
          showRegisterForm(rfid);
        } else {
          hideForm();
          showError(data.message || "Unknown response");
        }
        break;
    }
  } catch (err) {
    console.error("❌ FETCH ERROR:", err);
    hideForm();
    showError("Server Error");
  }
}

// -----------------------------
// REGISTER LOGIC
// -----------------------------
saveBtn.addEventListener("click", async () => {
  const first = firstInput.value.trim();
  const last = lastInput.value.trim();
  const phone = phoneInput.value.trim();

  if (!currentRFID) {
    showError("No RFID to register");
    return;
  }

  if (!first) {
    showWarning("First name required");
    firstInput.focus();
    return;
  }

  if (!last) {
    showWarning("Last name required");
    lastInput.focus();
    return;
  }

  console.log("📝 REGISTERING USER:", {
    rfid_uid: currentRFID,
    first_name: first,
    last_name: last,
    phone: phone
  });

  try {
    const res = await fetch(`${API_URL}/register`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        rfid_uid: currentRFID,
        first_name: first,
        last_name: last,
        phone: phone
      })
    });

    const data = await res.json();

    console.log("📥 REGISTER RESPONSE:", data);

    if (!res.ok) {
      showError(data.message || "Register failed");
      return;
    }

    if (data.status === "already_registered") {
      showWarning("RFID already registered");
      return;
    }

    if (data.success === true || data.status === "registered") {
      hideForm();

      showState({
        bg: "#16a34a",
        title: `${first} ${last}`,
        phone: phone ? `📞 ${phone}` : "",
        status: "✅ Registered Successfully"
      });

      currentRFID = null;
      return;
    }

    showError(data.message || "Register failed");
  } catch (err) {
    console.error("❌ REGISTER ERROR:", err);
    showError("Register Error");
  }
});

// -----------------------------
// INIT
// -----------------------------
window.onload = () => {
  resetUI();
  console.log("🔥 RFID App Ready");
};
