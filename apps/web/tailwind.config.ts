import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // Neutral fintech base. v0 can restyle freely; semantic names are what the
        // components reference so a palette swap does not require touching logic.
        surface: { DEFAULT: "#ffffff", muted: "#f8fafc", border: "#e2e8f0" },
        severity: {
          critical: "#b91c1c",
          high: "#c2410c",
          medium: "#a16207",
          low: "#0f766e",
        },
      },
    },
  },
  plugins: [],
};
export default config;
