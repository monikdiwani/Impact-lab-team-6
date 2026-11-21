import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// base "./" so the built site works from any folder or static host (GitHub Pages, Vercel, a USB stick)
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  // one bundle on purpose (about 260 KB gzipped, mostly recharts): no lazy chunks to fail on a slow venue network
  build: { chunkSizeWarningLimit: 1000 },
});
