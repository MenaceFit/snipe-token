/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#edfcf2",
          500: "#22c55e",
          600: "#16a34a",
        },
      },
    },
  },
  plugins: [],
};
