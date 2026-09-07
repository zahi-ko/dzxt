import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 所有 /api 请求在开发态由 Vite 转发到后端，生产态由 FastAPI 托管 dist 后同源访问。
// 因此前端代码里一律写相对路径 /api/...，不得硬编码端口。
// 默认后端 127.0.0.1:8000；端口被占用时可设 BACKEND_URL 覆盖，例：
//   BACKEND_URL=http://127.0.0.1:8899 npm run dev
const backendUrl = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: backendUrl,
        changeOrigin: true,
      },
      // 录音电平走 WebSocket，同样转发到后端；ws: true 才会升级协议
      '/ws': {
        target: backendUrl.replace(/^http/, 'ws'),
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
