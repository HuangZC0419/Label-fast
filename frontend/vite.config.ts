import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端端口通过环境变量传入，默认 3002（与 Docker 端口一致）
// 本地开发可通过 BACKEND_PORT=8000 覆盖
const backendPort = process.env.BACKEND_PORT || '3002'
const backendTarget = `http://127.0.0.1:${backendPort}`

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
      },
      '/minimind': {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
})
