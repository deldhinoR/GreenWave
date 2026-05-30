import { fetchJson } from "./api";

const AUTH_KEY = "gw_auth";

export function isAuthenticated() {
  return localStorage.getItem(AUTH_KEY) === "1";
}

export function markAuthenticated() {
  localStorage.setItem(AUTH_KEY, "1");
}

export function clearAuthentication() {
  localStorage.removeItem(AUTH_KEY);
}

export async function validateSession() {
  try {
    await fetchJson("/auth/me");
    markAuthenticated();
    return true;
  } catch (_err) {
    clearAuthentication();
    return false;
  }
}
