/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Google Sans"', 'Roboto', 'Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
      },
      colors: {
        google: {
          blue: "#1a73e8",
          bluedark: "#8ab4f8",
          red: "#ea4335",
          yellow: "#fbbc04",
          green: "#34a853",
          bgLight: "#f8fafd",
          bgDark: "#131314",
          surfaceLight: "#ffffff",
          surfaceDark: "#1e1f20",
          cardLight: "#f0f4f9",
          cardDark: "#28292a",
          borderLight: "#e0e3e7",
          borderDark: "#37393b",
          pillLight: "#c2e7ff",
          pillTextLight: "#001d35",
          pillDark: "#004a77",
          pillTextDark: "#c2e7ff",
        },
      },
    },
  },
  plugins: [require("daisyui")],
  daisyui: {
    themes: ["light", "dark"],
  },
}
