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
          950: "#f5f2eb",
          900: "#fbfaf7",
          850: "#ffffff",
          800: "#f0ede5",
          700: "#dedbd2",
          600: "#c6c3ba",
          500: "#a4a29a",
        },
        surface: {
          50: "#172522",
          100: "#20312d",
          200: "#30433e",
          300: "#52625d",
        },
        slate: {
          400: "#64736e",
          500: "#78837e",
          600: "#98a09b",
        },
        accent: {
          DEFAULT: "#0f766e",
          light: "#15988d",
          dark: "#0b5d57",
          muted: "rgba(15, 118, 110, 0.12)",
          subtle: "rgba(15, 118, 110, 0.06)",
        },
        verdict: {
          supported: "#27735d",
          partial: "#aa6a19",
          contradicted: "#b94a45",
          inconclusive: "#687773",
        },
      },
      fontFamily: {
        sans: [
          "DM Sans",
          "SF Pro Display",
          "-apple-system",
          "system-ui",
          "sans-serif",
        ],
        mono: ["JetBrains Mono", "SF Mono", "Menlo", "monospace"],
        display: [
          "Fraunces",
          "Georgia",
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
        glow: "0 8px 24px rgba(15, 118, 110, 0.12)",
        "inner-glow": "inset 0 1px 0 rgba(255,255,255,0.8)",
        card: "0 1px 3px rgba(32,49,45,0.06), 0 8px 24px rgba(32,49,45,0.04)",
        elevated:
          "0 12px 30px rgba(32,49,45,0.10), 0 2px 6px rgba(32,49,45,0.05)",
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