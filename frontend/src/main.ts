import { createApp } from 'vue'
// 字体离线自托管：不依赖任何外部 CDN，构建后随应用一起分发
import '@fontsource-variable/geist'
import '@fontsource-variable/geist-mono'
import '@fontsource/instrument-serif/400.css'
import '@fontsource/instrument-serif/400-italic.css'
import App from './App.vue'
import router from './router'
import './styles/app.css'

createApp(App).use(router).mount('#app')
