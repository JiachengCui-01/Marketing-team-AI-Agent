"use client";

import type { Locale } from "@/lib/i18n";

export type UserTheme = "light" | "dark" | "aurora" | "crystal";

const LOCALE_PREFIX = "marketing-agent-locale";
const THEME_PREFIX = "marketing-agent-theme";

export const DEFAULT_USER_LOCALE: Locale = "zh";
export const DEFAULT_USER_THEME: UserTheme = "light";

function scopedKey(prefix: string, account: string) {
  return `${prefix}:${account}`;
}

export function getUserLocale(account: string): Locale {
  if (typeof window === "undefined") return DEFAULT_USER_LOCALE;
  const stored = window.localStorage.getItem(scopedKey(LOCALE_PREFIX, account));
  return stored === "zh" || stored === "en" ? stored : DEFAULT_USER_LOCALE;
}

export function saveUserLocale(account: string, locale: Locale) {
  window.localStorage.setItem(scopedKey(LOCALE_PREFIX, account), locale);
}

export function getUserTheme(account: string): UserTheme {
  if (typeof window === "undefined") return DEFAULT_USER_THEME;
  const stored = window.localStorage.getItem(scopedKey(THEME_PREFIX, account));
  return stored === "light" || stored === "dark" || stored === "aurora" || stored === "crystal"
    ? stored
    : DEFAULT_USER_THEME;
}

export function saveUserTheme(account: string, theme: UserTheme) {
  window.localStorage.setItem(scopedKey(THEME_PREFIX, account), theme);
}
