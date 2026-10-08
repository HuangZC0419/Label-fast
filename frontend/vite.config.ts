import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

// 后端端口通过环境变量传入，默认 3002（与 Docker 端口一致）
// 本地开发可通过 set BACKEND_PORT=8000 覆盖
const backendPort = process.env.BACKEND_PORT || '3002'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
      },
      '/minimind': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
})