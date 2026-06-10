"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

export function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const active = mounted ? (resolvedTheme ?? theme) : "light";
  const next = active === "dark" ? "light" : "dark";

  return (
    <button
      onClick={() => setTheme(next)}
      aria-label="Toggle theme"
      className="p-2 rounded-md hover:bg-bg-subtle transition text-fg-muted hover:text-fg"
    >
      {mounted && active === "dark" ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}
