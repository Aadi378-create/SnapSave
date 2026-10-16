// For separate hosting, set this to the HTTPS backend origin before deployment.
window.SNAPSAVE_API_BASE = window.SNAPSAVE_API_BASE ||
  (["localhost", "127.0.0.1"].includes(location.hostname) ? "http://127.0.0.1:8000" : location.origin);
