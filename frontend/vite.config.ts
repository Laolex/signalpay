import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/signals":    "http://localhost:8000",
      "/discovery":  "http://localhost:8000",
      "/stats":      "http://localhost:8000",
      "/feed":       "http://localhost:8000",
      "/agent":      "http://localhost:8000",
      "/compliance": "http://localhost:8000",
      "/reputation": "http://localhost:8000",
      "/economics":  "http://localhost:8000",
      "/positions":  "http://localhost:8000",
      "/chains":     "http://localhost:8000",
      "/auction":    "http://localhost:8000",
      "/treasury":   "http://localhost:8000",
      "/stake":      "http://localhost:8000",
      "/governance":  "http://localhost:8000",
      "/subscribe":   "http://localhost:8000",
      "/pool":        "http://localhost:8000",
    },
  },
});
