import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#fff0f5",
          100: "#ffe1ec",
          200: "#ffc2d9",
          300: "#ffa3c6",
          400: "#ff8fab",
          500: "#ff6d96",
          600: "#f04577",
          700: "#c92f5e",
          800: "#9e2349",
          900: "#7a1a39",
        },
        ink: {
          50: "#f7f7fb",
          100: "#eceef5",
          200: "#d7dae6",
          300: "#b3b9cc",
          400: "#8890a8",
          500: "#656d87",
          600: "#4b5169",
          700: "#363b4e",
          800: "#232636",
          900: "#14151f",
          950: "#0a0a10",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
      },
      boxShadow: {
        soft: "0 1px 2px 0 rgb(0 0 0 / 0.04), 0 2px 8px -2px rgb(0 0 0 / 0.08)",
        card: "0 1px 3px 0 rgb(0 0 0 / 0.06), 0 8px 24px -8px rgb(0 0 0 / 0.12)",
      },
      borderRadius: {
        xl2: "1.25rem",
      },
      keyframes: {
        "fade-in": { "0%": { opacity: "0", transform: "translateY(4px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
      },
      animation: {
        "fade-in": "fade-in 0.35s ease-out",
      },
    },
  },
  plugins: [],
};

export default config;
