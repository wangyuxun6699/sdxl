import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { viteStaticCopy } from "vite-plugin-static-copy";

export default defineConfig({
  plugins: [
    vue(),
    viteStaticCopy({
      targets: [
        {
          src: "node_modules/cesium/Build/Cesium/Assets/**/*",
          dest: "cesium/Assets",
        },
        {
          src: "node_modules/cesium/Build/Cesium/ThirdParty/**/*",
          dest: "cesium/ThirdParty",
        },
        {
          src: "node_modules/cesium/Build/Cesium/Widgets/**/*",
          dest: "cesium/Widgets",
        },
        {
          src: "node_modules/cesium/Build/Cesium/Workers/**/*",
          dest: "cesium/Workers",
        },
      ],
    }),
  ],
  define: {
    CESIUM_BASE_URL: JSON.stringify("/cesium"),
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
