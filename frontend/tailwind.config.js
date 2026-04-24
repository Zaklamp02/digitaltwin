/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Light-first palette; single accent matching the CV.
        accent: {
          DEFAULT: "#0F766E", // teal-700; swap to CV accent when finalised
          fg: "#134E4A",
        },
        ink: "#0f172a",
        paper: "#fbfbf9",
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Inter",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
