import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api": "http://194.93.48.114:9000",
      "/ws": { target: "http://194.93.48.114:9000", ws: true },
    },
  },
  build: {
    outDir: "dist",
    assetsDir: "assets",
  },
});
