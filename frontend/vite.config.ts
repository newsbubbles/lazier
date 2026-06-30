import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend runs on :8000. Proxy API, static files, and the progress websocket.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/files": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
