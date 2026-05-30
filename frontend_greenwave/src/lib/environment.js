const THEME_KEY = "gw_theme";
const LANGUAGE_KEY = "gw_language";
const EVENT_NAME = "gw_environment_updated";

export function getTheme() {
  return localStorage.getItem(THEME_KEY) || "light";
}

export function getLanguage() {
  return localStorage.getItem(LANGUAGE_KEY) || "English (US)";
}

export function applyTheme(theme) {
  const normalized = theme === "dark" ? "dark" : "light";
  localStorage.setItem(THEME_KEY, normalized);
  document.documentElement.setAttribute("data-theme", normalized);
  return normalized;
}

export function applyLanguage(language) {
  const next = language || "English (US)";
  localStorage.setItem(LANGUAGE_KEY, next);
  return next;
}

export function applyEnvironment(theme, language) {
  const nextTheme = applyTheme(theme);
  const nextLanguage = applyLanguage(language);
  window.dispatchEvent(new CustomEvent(EVENT_NAME, { detail: { theme: nextTheme, language: nextLanguage } }));
  return { theme: nextTheme, language: nextLanguage };
}

export function environmentEventName() {
  return EVENT_NAME;
}
