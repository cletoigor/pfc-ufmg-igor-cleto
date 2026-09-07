// theme.js — light/dark switch. Light is the default and OS preference is
// deliberately not consulted (prefers-color-scheme): the app opens the same way
// on every machine, so a demo never depends on the host's settings. Dark is
// opt-in, remembered.
//
// The tokens are still written dark-first in styles.css (bare :root is dark,
// :root[data-theme="light"] overrides it), so "default light" means the page
// is *stamped* data-theme="light" unless storage says "dark" — see the inline
// script in index.html, which does the same before first paint.

// Bumped from "iot-copilot-theme" when the default flipped to light: the old
// build persisted the resolved theme on every boot, not just on a click, so
// every returning viewer had "dark" stored whether or not they ever chose it.
// A new key retires those, and only an actual toggle writes this one.
const STORAGE_KEY = "iot-copilot-theme-v2";

function writeStoredTheme(theme) {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Nothing to do — the toggle still works for the rest of the session.
  }
}

export function applyTheme(theme, { persist = true } = {}) {
  if (theme === "light") {
    document.documentElement.dataset.theme = "light";
  } else {
    delete document.documentElement.dataset.theme;
  }
  if (persist) writeStoredTheme(theme);

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
  // Syncing the button is not a choice the viewer made, so it must not write
  // storage — otherwise the default gets frozen in on first visit and a later
  // change to it would never reach anyone who had loaded the page once.
  const current = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  applyTheme(current, { persist: false });

  btn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    applyTheme(next);
    // The charts read colors via CSS var()s in SVG presentation attributes,
    // which re-resolve from the cascade on their own — no redraw needed.
  });
}
