import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 所有 /api 请求在开发态由 Vite 转发到后端，生产态由 FastAPI 托管 dist 后同源访问。
// 因此前端代码里一律写相对路径 /api/...，不得硬编码端口。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // 录音电平走 WebSocket，同样转发到后端；ws: true 才会升级协议
      '/ws': {
        target: 'ws://127.0.0.1:8000',
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
