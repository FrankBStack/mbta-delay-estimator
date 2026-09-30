import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // keeps everything on one origin in dev so CORS never comes up
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8010",
        changeOrigin: true,
      },
    },
  },
  build: {
    // the map library is most of the bundle and changes least; on its own
    // a deploy only invalidates the small app chunk for returning visitors
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (/node_modules[\/]maplibre-gl[\/]/.test(id)) return "maplibre";
          if (/node_modules[\/](react|react-dom|scheduler)[\/]/.test(id)) return "react";
          return undefined;
        },
      },
    },
  },
});
