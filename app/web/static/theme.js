// theme.js — dark/light switch. Dark is the default and OS preference is
// deliberately not consulted (prefers-color-scheme): the app must not open
// light on an unfamiliar machine mid-demo. Light is opt-in, remembered.

const STORAGE_KEY = "iot-copilot-theme";

function readStoredTheme() {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    // Private windows / disabled storage throw on access, not just on write.
    return null;
  }
}

function writeStoredTheme(theme) {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Nothing to do — the toggle still works for the rest of the session.
  }
}

export function applyTheme(theme) {
  if (theme === "light") {
    document.documentElement.dataset.theme = "light";
  } else {
    delete document.documentElement.dataset.theme;
  }
  writeStoredTheme(theme);

  const btn = document.getElementById("theme-toggle");
  if (btn) {
    btn.setAttribute("aria-pressed", String(theme === "light"));
    btn.title = theme === "light" ? "Switch to dark mode" : "Switch to light mode";
  }
}

export function wireThemeToggle() {
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;

  // The inline head script already stamped data-theme before first paint;
  // just sync the button state from what's on <html> now.
  const current = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  applyTheme(current);

  btn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    applyTheme(next);
    // The charts read colors via CSS var()s in SVG presentation attributes,
    // which re-resolve from the cascade on their own — no redraw needed.
  });
}
