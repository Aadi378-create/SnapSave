const API_BASE = (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') ? 'http://127.0.0.1:8000' : window.location.origin;

let idToken = null;
let auth = null;

async function getAuthToken() {
  if (typeof firebase !== "undefined" && firebase.auth && firebase.auth()) {
    const currentUser = firebase.auth().currentUser;
    if (currentUser) {
      return await currentUser.getIdToken();
    }
  }
  return localStorage.getItem("idToken");
}

async function apiRequest(endpoint, method = "GET", body = null) {
  const token = await getAuthToken();
  const options = {
    method,
    headers: {
      "Content-Type": "application/json",
    },
  };
  if (token) {
    options.headers.Authorization = `Bearer ${token}`;
  }
  if (body) options.body = JSON.stringify(body);

  const res = await fetch(`${API_BASE}${endpoint}`, options);
  if (!res.ok) {
    const errorData = await res
      .json()
      .catch(() => ({ detail: "Unknown server error" }));
    throw new Error(
      errorData.detail ||
        errorData.message ||
        `HTTP error! status: ${res.status}`
    );
  }
  return await res.json();
}

function setLoading(btnId, isLoading) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  if (isLoading) {
    btn.disabled = true;
    btn.dataset.originalHTML = btn.innerHTML;
    btn.innerHTML = `<span class="loading-spinner"></span> Loading...`;
  } else {
    btn.disabled = false;
    if (btn.dataset.originalHTML) {
      btn.innerHTML = btn.dataset.originalHTML;
    }
  }
}

function showAlert(containerId, msg, type) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = msg
    ? `<div class="alert alert-${type}"><i class="fa-solid ${type === "error" ? "fa-circle-exclamation" : "fa-circle-check"}"></i> ${msg}</div>`
    : "";
}
