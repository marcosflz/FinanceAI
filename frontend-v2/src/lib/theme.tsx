"use client";

import { useEffect, useSyncExternalStore, type ReactNode } from "react";

export type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "ft-theme";
const listeners = new Set<() => void>();
let currentTheme: Theme = "system";
let initialized = false;

function systemPrefersDark(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolvedTheme(theme: Theme): "light" | "dark" {
  if (theme === "system") return systemPrefersDark() ? "dark" : "light";
  return theme;
}

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  const resolved = resolvedTheme(theme);
  document.documentElement.classList.toggle("dark", resolved === "dark");
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
}

function emit() {
  for (const listener of listeners) listener();
}

function ensureInitialized() {
  if (initialized || typeof window === "undefined") return;
  initialized = true;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") {
    currentTheme = stored;
  }
  applyTheme(currentTheme);

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener(
    "change",
    () => {
      if (currentTheme === "system") {
        applyTheme("system");
        emit();
      }
    },
  );
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): Theme {
  return currentTheme;
}

function getServerSnapshot(): Theme {
  return "system";
}

export function setTheme(theme: Theme) {
  ensureInitialized();
  currentTheme = theme;
  window.localStorage.setItem(STORAGE_KEY, theme);
  applyTheme(theme);
  emit();
}

export function toggleTheme() {
  ensureInitialized();
  const next = resolvedTheme(currentTheme) === "dark" ? "light" : "dark";
  setTheme(next);
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const resolved = useSyncExternalStore(
    subscribe,
    () => resolvedTheme(currentTheme),
    () => "light" as const,
  );

  return { theme, resolved, setTheme, toggleTheme };
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    ensureInitialized();
  }, []);

  return children;
}

/**
 * Inline, render-blocking snippet that applies the persisted theme before
 * first paint. Kept tiny and dependency-free to avoid a light flash.
 */
export const themeScript = `(function(){try{var k="ft-theme";var t=localStorage.getItem(k);if(t!=="light"&&t!=="dark"&&t!=="system")t="system";var d=t==="dark"||(t==="system"&&window.matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d);document.documentElement.dataset.theme=d?"dark":"light";document.documentElement.style.colorScheme=d?"dark":"light";}catch(e){}})();`;

if (typeof window !== "undefined") {
  ensureInitialized();
}
