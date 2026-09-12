import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0a0a0f",
          900: "#0f0f17",
          850: "#14141f",
          800: "#1a1a27",
          700: "#24243a",
          600: "#33334d",
          500: "#4d4d6b",
        },
        surface: {
          50: "#fafaf9",
          100: "#f5f4f2",
          200: "#eceae6",
          300: "#ddd9d3",
        },
        slate: {
          400: "#8b8b9e",
          500: "#6b6b80",
          600: "#4f4f66",
        },
        accent: {
          DEFAULT: "#e89b2d",
          light: "#f0b95e",
          dark: "#c47e1a",
          muted: "rgba(232, 155, 45, 0.12)",
          subtle: "rgba(232, 155, 45, 0.06)",
        },
        verdict: {
          supported: "#34d399",
          partial: "#e89b2d",
          contradicted: "#f87171",
          inconclusive: "#8b8b9e",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "SF Pro Display",
          "-apple-system",
          "system-ui",
          "sans-serif",
        ],
        mono: ["JetBrains Mono", "SF Mono", "Menlo", "monospace"],
        display: [
          "Inter",
          "SF Pro Display",
          "-apple-system",
          "system-ui",
          "sans-serif",
        ],
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "0.875rem" }],
      },
      borderRadius: {
        "4xl": "2rem",
      },
      boxShadow: {
        glow: "0 0 20px rgba(232, 155, 45, 0.15)",
        "inner-glow": "inset 0 1px 0 rgba(255,255,255,0.04)",
        card: "0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2)",
        elevated:
          "0 4px 16px rgba(0,0,0,0.4), 0 2px 4px rgba(0,0,0,0.3)",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.5s ease-out forwards",
        "slide-up": "slideUp 0.4s ease-out forwards",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;