import { createRouter, createWebHistory } from 'vue-router'
import { authState, ensureAuthReady, isAuthenticated } from '../composables/useAuth'

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    guestOnly?: boolean
    title?: string
  }
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { guestOnly: true, title: '登录' },
    },
    {
      path: '/app',
      component: () => import('../layouts/AppLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          redirect: { name: 'text-annotation' },
        },
        {
          path: 'text',
          name: 'text-annotation',
          component: () => import('../views/TextAnnotationView.vue'),
          meta: { title: '文本标注' },
        },
        {
          path: 'image',
          name: 'image-annotation',
          component: () => import('../views/ImageAnnotationView.vue'),
          meta: { title: '图像标注' },
        },
        {
          path: 'qa',
          name: 'qa-annotation',
          component: () => import('../views/QaAnnotationView.vue'),
          meta: { title: '大模型问答标注' },
        },
        {
          path: 'classify',
          name: 'standard-classify',
          component: () => import('../modules/gb-fenlei/views/StandardClassifyView.vue'),
          meta: { title: '航空标准分类' },
        },
        {
          path: 'mixed',
          name: 'mixed-annotation',
          component: () => import('../modules/mixed-annotation/views/MixedAnnotationView.vue'),
          meta: { title: '混合标注' },
        },
        {
          path: 'model',
          name: 'model-annotation',
          component: () => import('../modules/model-annotation/views/ModelAnnotationView.vue'),
          meta: { title: '模型标注' },
        },
      ],
    },
    {
      path: '/',
      redirect: () => (authState.token ? '/app/text' : '/login'),
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/',
    },
  ],
})

router.beforeEach(async (to) => {
  await ensureAuthReady()

  if (to.meta.requiresAuth && !isAuthenticated.value) {
    return { name: 'login', replace: true }
  }

  if (to.meta.guestOnly && isAuthenticated.value) {
    return { name: 'text-annotation', replace: true }
  }

  return true
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} · 数据标注与分类工具` : '数据标注与分类工具 标注平台'
})

export default router
