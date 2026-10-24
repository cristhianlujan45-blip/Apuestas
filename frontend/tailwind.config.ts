import type { Config } from "tailwindcss";

// Tokens alineados con la paleta validada (modo oscuro) de la guía de visualización.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        page: "#0d0d0d",
        surface: { 1: "#1a1a19", 2: "#222220", 3: "#2c2c2a" },
        line: { DEFAULT: "#2c2c2a", strong: "#383835" },
        ink: { DEFAULT: "#f0efec", 2: "#c3c2b7", muted: "#898781" },
        series: {
          1: "#3987e5", 2: "#d95926", 3: "#199e70", 4: "#c98500",
          5: "#d55181", 6: "#008300", 7: "#9085e9", 8: "#e66767",
        },
        good: "#0ca30c",
        warning: "#fab219",
        serious: "#ec835a",
        critical: "#d03b3b",
        accent: "#3987e5",
      },
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
