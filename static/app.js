// -----------------------------
// CONFIG
// -----------------------------
const API_URL = "";
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

let currentRFID = null;
let scanTimeout = null;

// -----------------------------
// SMART AUTO FOCUS (FIXED)
// -----------------------------
function focusInput() {
  scanInput.focus();
}

// Only focus scanner when clicking OUTSIDE form
document.addEventListener("click", (e) => {
  const isInsideForm = e.target.closest("#registerForm");

  if (!isInsideForm) {
    focusInput();
  }
});

// Prevent click interruption edge case
saveBtn.addEventListener("mousedown", (e) => {
  e.stopPropagation();
});

// -----------------------------
// SCAN HANDLER
// -----------------------------
scanInput.addEventListener("input", (e) => {
  const value = e.target.value;

  clearTimeout(scanTimeout);

  scanTimeout = setTimeout(() => {
    if (value.length > 0) {
      handleScan(value.trim());
      scanInput.value = "";
    }
  }, 100);
});

// -----------------------------
// HANDLE SCAN
// -----------------------------
async function handleScan(rfid) {
  console.log("Scanned:", rfid);

  try {
    const res = await fetch(`${API_URL}/scan`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ rfid_uid: rfid })
    });

    const data = await res.json();

    if (data.found) {
      hideForm();
      showSuccess(data);
    } else {
      showRegisterForm(data.rfid_uid);
    }

  } catch (err) {
    console.error(err);
    showError("Server Error");
  }
}

// -----------------------------
// SHOW REGISTER FORM
// -----------------------------
function showRegisterForm(rfid) {
  currentRFID = rfid;

  resultBox.style.background = "#2563eb";

  nameEl.innerText = "New Bracelet Detected";
  phoneEl.innerText = "";
  statusEl.innerText = "Enter student info";

  formBox.style.display = "block";

  firstInput.value = "";
  lastInput.value = "";
  phoneInput.value = "";

  firstInput.focus();
}

// -----------------------------
// SAVE USER
// -----------------------------
saveBtn.addEventListener("click", async () => {
  const first = firstInput.value.trim();
  const last = lastInput.value.trim();
  const phone = phoneInput.value.trim();

  if (!first) {
    alert("First name required");
    return;
  }

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

    if (data.error || data.success === false) {
      showError("Already Registered");
      return;
    }

    hideForm();

    showSuccess({
      first_name: first,
      last_name: last,
      phone: phone
    });

  } catch (err) {
    console.error(err);
    showError("Register Error");
  }
});

// -----------------------------
// UI STATES
// -----------------------------
function showSuccess(data) {
  resultBox.style.background = "#16a34a";

  nameEl.innerText = `${data.first_name} ${data.last_name}`;
  phoneEl.innerText = data.phone ? `📞 ${data.phone}` : "";
  statusEl.innerText = "✅ Checked In";

  flashReset();
}

function showError(message) {
  resultBox.style.background = "#dc2626";

  nameEl.innerText = "Error";
  phoneEl.innerText = "";
  statusEl.innerText = `❌ ${message}`;

  flashReset();
}

// -----------------------------
// FORM CONTROL
// -----------------------------
function hideForm() {
  formBox.style.display = "none";
}

// -----------------------------
// RESET UI
// -----------------------------
function flashReset() {
  setTimeout(() => {
    resultBox.style.background = "#1f2937";
    nameEl.innerText = "Scan RFID Bracelet";
    phoneEl.innerText = "";
    statusEl.innerText = "";
  }, 3000);
}

// -----------------------------
// INIT
// -----------------------------
window.onload = () => {
  focusInput();
  console.log("RFID App Ready");
};