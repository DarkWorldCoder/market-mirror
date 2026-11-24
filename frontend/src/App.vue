<template>
  <router-view />
</template>

<script setup>
// 使用 Vue Router 来管理页面
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

#app {
  font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: inherit;
  background-color: transparent;
}

/* Native selects, date pickers and the page scrollbar follow the theme instead
   of staying light on a dark page. */
html {
  color-scheme: light;
}

html[data-theme='dark'] {
  color-scheme: dark;
  background-color: #161719;
}

.ws,
.ws-overlay,
.mm-auth {
  color-scheme: light;
}

.ws[data-theme='dark'],
.ws-overlay[data-theme='dark'],
.mm-auth[data-theme='dark'] {
  color-scheme: dark;
}

/* 全局按钮样式 */
button {
  font-family: inherit;
}
</style>
