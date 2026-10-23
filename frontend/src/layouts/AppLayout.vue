<script setup lang="ts">
import { RouterView } from 'vue-router'
import AppHeader from '../components/AppHeader.vue'
import AppNavRail from '../components/AppNavRail.vue'
import ToastHost from '../components/ToastHost.vue'
</script>

<template>
  <div class="app-container app-page">
    <AppNavRail />

    <div class="app-body">
      <AppHeader />

      <main class="app-main">
        <RouterView v-slot="{ Component, route }">
          <Transition name="page" mode="out-in">
            <component :is="Component" :key="route.path" />
          </Transition>
        </RouterView>
      </main>
    </div>

    <ToastHost />
  </div>
</template>
