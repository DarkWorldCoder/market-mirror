<template>
  <header v-if="legacy" class="mm-legacy-bar">
    <RouterLink to="/" class="mm-legacy-brand">← MarketMirror workspace</RouterLink>
    <span>Legacy view</span>
  </header>
  <router-view />
</template>

<script setup>
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
// 使用 Vue Router 来管理页面
const route = useRoute()
const LEGACY_PAGES = new Set(['LegacyHome', 'Process', 'Simulation', 'SimulationRun', 'Report', 'Interaction'])
const legacy = computed(() => LEGACY_PAGES.has(route.name))
</script>

<style>
/* 全局样式重置 */
@layer base {
  * {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }
}

.mm-legacy-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 18px;
  border-bottom: 1px solid #e6e6e1;
  background: #f6f8f6;
  color: #202623;
  font: 13px/1.5 'Geist', ui-sans-serif, system-ui, sans-serif;
}

.mm-legacy-bar a {
  color: inherit;
  font-weight: 550;
  text-underline-offset: 4px;
}

#app {
  font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: #000000;
  background-color: #ffffff;
}

/* 滚动条样式 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: #f1f1f1;
}

::-webkit-scrollbar-thumb {
  background: #000000;
}

::-webkit-scrollbar-thumb:hover {
  background: #333333;
}

/* 全局按钮样式 */
button {
  font-family: inherit;
}
</style>
