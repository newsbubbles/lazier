import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend runs on :5181. Proxy API, static files, and the progress websocket.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    strictPort: true,   // fail loudly rather than drift to 5181/5182 if 5180 is taken
    proxy: {
      "/api": "http://localhost:5181",
      "/files": "http://localhost:5181",
      "/ws": { target: "ws://localhost:5181", ws: true },
    },
  },
});
