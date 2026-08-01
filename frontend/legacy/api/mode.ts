/**
 * Demo-mode switch. Defaults to OFF (talk to the real API at the same
 * origin) — this only exists so every screen is demonstrable before M8's
 * backend is deployed, per the M9 brief. Toggle with the header switch, or
 * open the app with `?mock=1` once; the choice persists for the tab via
 * `sessionStorage` so client-side navigation (and a refresh, which is the
 * exact scenario the resumable-progress feature needs to survive) keeps it.
 */
const STORAGE_KEY = "eduforge:demo-mode";

type Listener = (enabled: boolean) => void;
const listeners = new Set<Listener>();

function readInitial(): boolean {
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.has("mock")) {
      const value = params.get("mock") !== "0";
      window.sessionStorage.setItem(STORAGE_KEY, value ? "1" : "0");
      return value;
    }
    return window.sessionStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

let enabled = typeof window !== "undefined" ? readInitial() : false;

export function isMockMode(): boolean {
  return enabled;
}

export function setMockMode(value: boolean): void {
  enabled = value;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, value ? "1" : "0");
  } catch {
    // sessionStorage unavailable (e.g. private mode edge cases) — in-memory
    // flag still works for the current page life.
  }
  listeners.forEach((listener) => listener(enabled));
}

export function subscribeMockMode(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
