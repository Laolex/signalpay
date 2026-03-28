import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/signals": "https://signalpay-production.up.railway.app",
      "/discovery": "https://signalpay-production.up.railway.app",
      "/stats": "https://signalpay-production.up.railway.app",
      "/feed": "https://signalpay-production.up.railway.app",
      "/agent": "https://signalpay-production.up.railway.app",
    },
  },
});
