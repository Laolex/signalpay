import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/signals": "http://localhost:8000",
      "/discovery": "http://localhost:8000",
      "/stats": "http://localhost:8000",
      "/feed": "http://localhost:8000",
      "/agent": "http://localhost:8000",
    },
  },
});
