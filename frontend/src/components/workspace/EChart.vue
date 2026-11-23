<template>
  <figure class="ws-chart" :style="{ height: height + 'px' }">
    <div ref="el" class="ws-chart-canvas" role="img" :aria-label="label"></div>
    <figcaption v-if="caption" class="ws-note">{{ caption }}</figcaption>
  </figure>
</template>

<script setup>
// Apache ECharts in a component: loaded on demand (its own chunk), resized with its box, re-themed when the
// workspace theme changes.
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  option: { type: Object, default: null },
  height: { type: Number, default: 260 },
  label: { type: String, default: 'Chart' },
  caption: { type: String, default: '' },
  theme: { type: String, default: '' }
})
const el = ref(null)
let chart = null
let observer = null

async function render() {
  if (!el.value || !props.option) return
  const echarts = await import('echarts')
  if (!chart) chart = echarts.init(el.value, null, { renderer: 'svg' })
  chart.setOption(props.option, true)
}

onMounted(() => {
  render()
  observer = new ResizeObserver(() => chart && chart.resize())
  observer.observe(el.value)
})
watch(() => [props.option, props.theme], render)
onBeforeUnmount(() => {
  observer && observer.disconnect()
  chart && chart.dispose()
})
</script>

<style scoped>
.ws-chart {
  margin: 0;
  display: flex;
  flex-direction: column;
}
.ws-chart-canvas {
  flex: 1;
  min-height: 0;
  width: 100%;
}
</style>
