/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: "#111315",
          panel: "#16181b",
          raised: "#1c1f22",
        },
        border: {
          DEFAULT: "#2a2d31",
        },
        accent: {
          DEFAULT: "#22c55e",
          muted: "#16a34a",
          dim: "rgba(34, 197, 94, 0.12)",
        },
        warn: {
          DEFAULT: "#d97706",
          dim: "rgba(217, 119, 6, 0.12)",
        },
        danger: {
          DEFAULT: "#ef4444",
          dim: "rgba(239, 68, 68, 0.1)",
        },
        text: {
          DEFAULT: "#f4f4f5",
          muted: "#9ca3af",
          faint: "#6b7280",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      borderRadius: {
        DEFAULT: "10px",
      },
    },
  },
  plugins: [],
};
