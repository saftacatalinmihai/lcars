import { defineConfig } from "vite";

// Relative asset paths: the packed .ehpk is unzipped and loaded from a
// file-ish base by the Even App WebView, so absolute "/assets/..." URLs would
// not resolve.
export default defineConfig({
  base: "./",
  build: {
    outDir: "dist",
    target: "es2022",
    // One file each: the packer ships a directory, and fewer requests through
    // the WebView is fewer things to go wrong on a cold start.
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "app-[hash].js",
        assetFileNames: "app.[ext]",
      },
    },
  },
});
