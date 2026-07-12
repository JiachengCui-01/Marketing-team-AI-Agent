import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: "rgb(var(--bg) / <alpha-value>)",
          subtle: "rgb(var(--bg-subtle) / <alpha-value>)",
          elevated: "rgb(var(--bg-elevated) / <alpha-value>)",
        },
        fg: {
          DEFAULT: "rgb(var(--fg) / <alpha-value>)",
          muted: "rgb(var(--fg-muted) / <alpha-value>)",
          subtle: "rgb(var(--fg-subtle) / <alpha-value>)",
        },
        border: "rgb(var(--border) / <alpha-value>)",
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          fg: "rgb(var(--accent-fg) / <alpha-value>)",
        },
        success: "rgb(var(--success) / <alpha-value>)",
        warn: "rgb(var(--warn) / <alpha-value>)",
        danger: "rgb(var(--danger) / <alpha-value>)",
        // Feature-identity hues (used only on module identity icons, kept restrained).
        "feature-news": "rgb(var(--feature-news) / <alpha-value>)",
        "feature-image": "rgb(var(--feature-image) / <alpha-value>)",
        "feature-content": "rgb(var(--feature-content) / <alpha-value>)",
        "feature-analytics": "rgb(var(--feature-analytics) / <alpha-value>)",
        "feature-research": "rgb(var(--feature-research) / <alpha-value>)",
      },
      borderRadius: {
        // macOS-softer scale (bumps existing rounded-* usages system-wide).
        lg: "0.625rem", // 10px — controls/buttons/inputs
        xl: "0.875rem", // 14px — cards / input clusters
        "2xl": "1.125rem", // 18px — floating panels / modals
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      transitionTimingFunction: {
        macos: "cubic-bezier(.32,.72,0,1)",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "dot-pulse": {
          "0%, 80%, 100%": { opacity: "0.2" },
          "40%": { opacity: "1" },
        },
        "dot-drift": {
          "0%, 100%": { opacity: "0.35", transform: "translateY(0) scale(0.88)" },
          "50%": { opacity: "1", transform: "translateY(-3px) scale(1.1)" },
        },
        "float-soft": {
          "0%, 100%": { transform: "translateY(0) rotate(0deg)", opacity: "0.8" },
          "50%": { transform: "translateY(-2px) rotate(2deg)", opacity: "1" },
        },
        "scale-in": {
          from: { opacity: "0", transform: "scale(0.92)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "rail-sweep": {
          "0%": { transform: "translateX(-120%)", opacity: "0" },
          "15%": { opacity: "1" },
          "85%": { opacity: "1" },
          "100%": { transform: "translateX(120%)", opacity: "0" },
        },
        "pulse-ring": {
          "0%": { boxShadow: "0 0 0 0px rgb(var(--accent) / 0.4)" },
          "70%": { boxShadow: "0 0 0 10px rgb(var(--accent) / 0)" },
          "100%": { boxShadow: "0 0 0 0px rgb(var(--accent) / 0)" },
        },
        "bounce-in": {
          "0%": { opacity: "0", transform: "scale(0.95) translateY(2px)" },
          "50%": { opacity: "1", transform: "scale(1.05)" },
          "100%": { opacity: "1", transform: "scale(1) translateY(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in 280ms cubic-bezier(.32,.72,0,1)",
        "dot-pulse": "dot-pulse 1.4s infinite ease-in-out",
        "dot-drift": "dot-drift 1.2s infinite ease-in-out",
        "float-soft": "float-soft 2s infinite ease-in-out",
        "scale-in": "scale-in 200ms cubic-bezier(.32,.72,0,1)",
        shimmer: "shimmer 1.8s infinite",
        "rail-sweep": "rail-sweep 1.8s infinite ease-in-out",
        "pulse-ring": "pulse-ring 1.5s infinite",
        "bounce-in": "bounce-in 400ms cubic-bezier(.34,.69,.78,.92)",
      },
    },
  },
  plugins: [],
};

export default config;
