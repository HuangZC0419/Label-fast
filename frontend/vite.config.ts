import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端端口通过环境变量传入，默认 3002（与 Docker 端口一致）
// 本地开发可通过 BACKEND_PORT=8000 覆盖
const backendPort = process.env.BACKEND_PORT || '3002'
const backendTarget = `http://127.0.0.1:${backendPort}`

// 国标（GB_fenlei）后端独立运行，默认 8000 端口
// 通过 GB_BACKEND_PORT 覆盖；前端 /gb-api 前缀会被剥离后转发
const gbBackendPort = process.env.GB_BACKEND_PORT || '8000'
const gbBackendTarget = `http://127.0.0.1:${gbBackendPort}`

// 混合标注后端独立运行，默认 3200 端口
// 通过 MIX_BACKEND_PORT 覆盖；前端 /mix-api 前缀会被剥离后转发
const mixBackendPort = process.env.MIX_BACKEND_PORT || '3200'
const mixBackendTarget = `http://127.0.0.1:${mixBackendPort}`

// 模型标注后端独立运行，默认 8267 端口
// 通过 MODEL_BACKEND_PORT 覆盖；前端 /model-api 前缀会被剥离后转发
const modelBackendPort = process.env.MODEL_BACKEND_PORT || '8267'
const modelBackendTarget = `http://127.0.0.1:${modelBackendPort}`

// 前端端口默认从 5175 开始；5175 被占用时 Vite 会自动顺延 5176、5177 …
// start.bat 探测到空闲端口后会通过 FRONTEND_PORT 传入
const frontendPort = Number(process.env.FRONTEND_PORT || 5175)

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: frontendPort,
    // 不开启 strictPort：端口被抢占时继续自动递增，而不是直接报错退出
    strictPort: false,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
      },
      '/minimind': {
        target: backendTarget,
        changeOrigin: true,
      },
      '/gb-api': {
        target: gbBackendTarget,
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/gb-api/, ''),
      },
      '/mix-api': {
        target: mixBackendTarget,
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/mix-api/, ''),
      },
      '/model-api': {
        target: modelBackendTarget,
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/model-api/, ''),
      },
    },
  },
})
