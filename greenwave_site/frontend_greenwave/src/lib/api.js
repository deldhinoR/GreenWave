const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:5000";

export function buildIntersectionId(regionId) {
  const raw = String(regionId || "").trim();
  if (!raw) return "INT-001";
  if (raw.startsWith("INT-")) return raw;
  const digits = raw.replace(/\D/g, "") || "1";
  return `INT-${digits.padStart(3, "0")}`;
}

export async function fetchJson(path, options = {}) {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const response = await fetch(url, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch (_err) {
    payload = null;
  }
  if (!response.ok) {
    const message = payload?.error || `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

export { API_BASE };

