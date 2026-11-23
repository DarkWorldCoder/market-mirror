<template>
  <figure class="ws-3d" :style="{ height: height + 'px' }">
    <div ref="el" class="ws-3d-canvas" role="img" :aria-label="label"></div>
    <div class="ws-3d-tools">
      <button type="button" class="ws-chip" :aria-pressed="spinning" @click="toggleSpin">{{ spinning ? 'Pause turning' : 'Turn' }}</button>
      <button type="button" class="ws-chip" @click="reset">Reset view</button>
    </div>
  </figure>
</template>

<script setup>
// The market in 3D with 3d-force-graph (three.js), loaded on demand in its own chunk. People are dots coloured by
// segment, linked to their segment hub and their communities; diamonds of the market map are its entities.
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  data: { type: Object, default: null },
  height: { type: Number, default: 440 },
  label: { type: String, default: '3D market' },
  theme: { type: String, default: 'dark' }
})
const el = ref(null), spinning = ref(true)
let fg = null, observer = null
const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

const bg = () => getComputedStyle(el.value.closest('.ws') || document.body).getPropertyValue('--panel').trim() || '#161719'
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])

async function render() {
  if (!el.value || !props.data) return
  if (!fg) {
    const { default: ForceGraph3D } = await import('3d-force-graph')
    fg = new ForceGraph3D(el.value, { controlType: 'orbit' })
      .showNavInfo(false)
      .enableNodeDrag(false)
      .nodeId('id')
      .nodeVal('val')
      .nodeRelSize(5)
      .nodeColor('color')
      .nodeOpacity(0.95)
      .nodeResolution(10)
      .nodeLabel((n) => `<div class="ws-3d-tip"><b>${esc(n.name)}</b><br>${esc(n.kind)}${n.detail ? ' · ' + esc(n.detail) : ''}</div>`)
      .linkColor((l) => l.color)
      .linkOpacity(0.35)
      .linkWidth((l) => (l.kind === 'community' ? 0.5 : l.kind === 'map' ? 0.8 : 0))
      .linkLabel((l) => (l.label ? esc(l.label) : ''))
      .d3VelocityDecay(0.3)
      .cooldownTicks(120)
      .onEngineStop(fit)
    fg.d3Force('charge').strength(-26)
    const controls = fg.controls()
    controls.autoRotate = spinning.value = !reduced
    controls.autoRotateSpeed = 1.1
  }
  fg.backgroundColor(bg()).width(el.value.clientWidth).height(el.value.clientHeight)
  fg.__fitted = false
  fg.graphData({ nodes: props.data.nodes.map((n) => ({ ...n })), links: props.data.links.map((l) => ({ ...l })) })
  setTimeout(fit, 2500) // the layout keeps settling; frame it once it has mostly spread out
}
function fit() {
  if (fg && !fg.__fitted) {
    fg.__fitted = true
    fg.zoomToFit(600, 12)
  }
}

function toggleSpin() {
  spinning.value = !spinning.value
  if (fg) fg.controls().autoRotate = spinning.value
}
function reset() {
  fg && fg.zoomToFit(500, 12)
}

onMounted(() => {
  render()
  observer = new ResizeObserver(() => fg && el.value && fg.width(el.value.clientWidth).height(el.value.clientHeight))
  observer.observe(el.value)
})
watch(() => props.data, render)
watch(() => props.theme, () => fg && el.value && setTimeout(() => fg.backgroundColor(bg()), 0))
onBeforeUnmount(() => {
  observer && observer.disconnect()
  if (fg) {
    fg.pauseAnimation()
    fg._destructor && fg._destructor()
    fg = null
  }
})
</script>

<style>
.ws-3d {
  margin: 0;
  position: relative;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--line);
}
.ws-3d-canvas {
  width: 100%;
  height: 100%;
}
.ws-3d-tools {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  gap: 6px;
}
.ws-3d-tools .ws-chip {
  font-size: 11.5px;
  padding: 3px 9px;
}
.ws-3d-tip {
  font: 12px/1.4 inherit;
  background: rgba(20, 20, 22, 0.92);
  color: #ececec;
  padding: 6px 8px;
  border-radius: 8px;
}
</style>
