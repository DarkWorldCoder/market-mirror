<template>
  <router-view />
  <div v-if="accountError" class="mm-server-down" role="alert">
    <h1>Cannot reach the server</h1>
    <p>{{ accountError }}</p>
    <button type="button" @click="retry">Retry</button>
  </div>
</template>

<script setup>
// 使用 Vue Router 来管理页面
import { accountError, loadAccount } from './workspace/account.js'
function retry() { loadAccount().then(() => { if (!accountError.value) location.reload() }) }
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

.mm-server-down {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 24px;
  text-align: center;
  background: #f6f8f6;
  color: #202623;
  font: 14px/1.6 'Geist', ui-sans-serif, system-ui, sans-serif;
}

.mm-server-down h1 { font-size: 22px; font-weight: 600; }
.mm-server-down p { max-width: 360px; color: #5d665f; }
.mm-server-down button {
  padding: 9px 16px;
  border: 1px solid #d8ded9;
  border-radius: 9px;
  background: #fff;
  color: inherit;
  font: inherit;
  cursor: pointer;
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
