/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Light, enterprise-SaaS palette. Conservative on purpose.
      // No "cool" colors, no defense-tech dark HUD. Reads like Linear / Notion /
      // a Govt of India dashboard. The Brigadier's staff officer should feel
      // they've used something like this before.
      colors: {
        // Surfaces
        canvas: "#ffffff",            // page background
        surface: "#f8fafc",           // panel background (slate-50)
        "surface-alt": "#f1f5f9",     // alternate panel (slate-100)

        // Text
        ink: "#0f172a",               // primary text (slate-900)
        "ink-muted": "#475569",       // secondary text (slate-600)
        "ink-faint": "#94a3b8",       // tertiary / labels (slate-400)

        // Borders / dividers
        line: "#e2e8f0",              // standard border (slate-200)
        "line-strong": "#cbd5e1",     // emphasized border (slate-300)

        // Single accent — used sparingly. Conservative blue, not vibrant.
        accent: "#2563eb",            // blue-600
        "accent-hover": "#1d4ed8",    // blue-700
        "accent-soft": "#eff6ff",     // blue-50

        // Status colors — desaturated, not alarming.
        // Used for post status pills and route closure indicators.
        "status-ok": "#16a34a",
        "status-ok-soft": "#f0fdf4",
        "status-watch": "#ca8a04",
        "status-watch-soft": "#fefce8",
        "status-critical": "#dc2626",
        "status-critical-soft": "#fef2f2",
        "status-imminent": "#991b1b",
        "status-imminent-soft": "#fee2e2",
        "status-unknown": "#64748b",
        "status-unknown-soft": "#f1f5f9",
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      fontSize: {
        xs: ["0.75rem", { lineHeight: "1rem" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.875rem", { lineHeight: "1.375rem" }],
        lg: ["1rem", { lineHeight: "1.5rem" }],
        xl: ["1.125rem", { lineHeight: "1.625rem" }],
        "2xl": ["1.375rem", { lineHeight: "1.875rem" }],
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)",
        panel: "0 1px 2px 0 rgb(15 23 42 / 0.05)",
      },
      borderRadius: {
        DEFAULT: "0.375rem",
        md: "0.5rem",
        lg: "0.625rem",
      },
    },
  },
  plugins: [],
};
