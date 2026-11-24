<template>
  <div ref="root" class="rwm" :class="{ dark: theme === 'dark', full: isFull }">
    <div ref="el" class="rwm-canvas" :style="{ height: height + 'px' }" role="region" :aria-label="label" tabindex="0"></div>
    <div v-if="$slots.overlay" class="rwm-overlay"><slot name="overlay" /></div>
    <div v-if="$slots.corner" class="rwm-corner"><slot name="corner" /></div>
    <div v-if="!failed" class="rwm-ctrls" role="toolbar" aria-label="Map controls">
      <div class="rwm-ctrl-group">
        <button type="button" aria-label="Zoom in" title="Zoom in" @click="map?.zoomIn()"><Plus :size="16" /></button>
        <button type="button" aria-label="Zoom out" title="Zoom out" @click="map?.zoomOut()"><Minus :size="16" /></button>
      </div>
      <button type="button" class="rwm-ctrl" :aria-pressed="tilted" :title="tilted ? 'Flat view' : 'Tilt to 3D'" :aria-label="tilted ? 'Flat view' : 'Tilt to 3D'" @click="toggleTilt"><span class="rwm-3d">{{ tilted ? '2D' : '3D' }}</span></button>
      <button type="button" class="rwm-ctrl" aria-label="Point north" title="Point north" @click="map?.resetNorthPitch(); tilted = false"><Compass :size="16" :style="{ transform: `rotate(${-bearing}deg)` }" /></button>
      <button type="button" class="rwm-ctrl" aria-label="Show everyone" title="Show everyone" @click="fitAll"><Locate :size="16" /></button>
      <button type="button" class="rwm-ctrl" :aria-label="isFull ? 'Exit full screen' : 'Full screen'" :title="isFull ? 'Exit full screen' : 'Full screen'" @click="toggleFull"><Minimize2 v-if="isFull" :size="16" /><Maximize2 v-else :size="16" /></button>
    </div>
    <p v-if="failed" class="rwm-fail" role="status">{{ failed }}</p>
    <p v-else-if="fellBack" class="rwm-offline" role="status">The street map could not load, so this is the offline map.</p>
  </div>
</template>

<script setup>
// A real, zoomable world map on MapLibre GL (BSD-3, open source). Street and dark styles come from OpenFreeMap
// (OpenStreetMap data, no key); satellite is NASA's Blue Marble (public domain); "Simple" is drawn from the bundled
// Natural Earth countries and works offline. People are points, interactions are great-circle arcs with a moving
// head, answers to the brand are pulsing rings, and an optional heat layer shows where weighted points cluster.
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { Compass, Locate, Maximize2, Minimize2, Minus, Plus } from 'lucide-vue-next'
import 'maplibre-gl/dist/maplibre-gl.css'
import { countries } from '../../workspace/audienceGeography'
import { greatCircle } from '../../workspace/cityPlace'
import { DEFAULT_MAP_CONFIG, allowedBasemap, loadMapConfig } from '../../workspace/mapConfig'

const props = defineProps({
  points: { type: Array, default: () => [] }, // { id, lon, lat, color, title, sub, size?, dim?, selected?, weight? }
  arcs: { type: Array, default: () => [] }, // { from:[lon,lat], to:[lon,lat], color, past? }
  pulses: { type: Array, default: () => [] }, // { lon, lat, color }
  basemap: { type: String, default: 'auto' }, // auto | streets | dark | satellite | simple
  globe: Boolean,
  heat: Boolean,
  cluster: Boolean,
  mixKeys: { type: Array, default: () => [] }, // [{ key, color }]: clusters draw as donuts of each point's `mix` key
  theme: { type: String, default: 'light' },
  height: { type: Number, default: 360 },
  label: { type: String, default: 'World map' }
})
const emit = defineEmits(['select', 'basemap-fallback'])
const el = ref(null), root = ref(null), failed = ref(''), fellBack = ref(false), tilted = ref(false), bearing = ref(0), isFull = ref(false)
const map = shallowRef(null)
let m = null // the MapLibre map; `map` mirrors it for the template
let maplibre = null, popup = null, raf = 0, disposed = false, fitted = false, styleKey = '', observer = null
const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

// tile hosts come from the server (MM_MAP_TILES); "off" leaves only the offline map and makes no outside requests
let cfg = DEFAULT_MAP_CONFIG
const withGlyphs = (style) => (cfg.glyphs ? { ...style, glyphs: cfg.glyphs } : style)
function simpleStyle(dark) {
  return withGlyphs({
    version: 8,
    sources: { countries: { type: 'geojson', data: { type: 'FeatureCollection', features: countries }, attribution: 'Natural Earth' } },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': dark ? '#11171c' : '#eef3f6' } },
      { id: 'land', type: 'fill', source: 'countries', paint: { 'fill-color': dark ? '#1f2a33' : '#dfe8e3' } },
      { id: 'borders', type: 'line', source: 'countries', paint: { 'line-color': dark ? '#3a4a55' : '#b9c7bf', 'line-width': 0.6 } }
    ]
  })
}
function satelliteStyle() {
  return withGlyphs({
    version: 8,
    sources: {
      bm: { type: 'raster', tileSize: 256, maxzoom: 8, attribution: cfg.satellite_attribution || '', tiles: [cfg.satellite] },
      countries: { type: 'geojson', data: { type: 'FeatureCollection', features: countries } }
    },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': '#05080c' } },
      { id: 'sat', type: 'raster', source: 'bm' },
      { id: 'borders', type: 'line', source: 'countries', paint: { 'line-color': 'rgba(255,255,255,.35)', 'line-width': 0.5 } }
    ]
  })
}
function fromTileHost(src) {
  if (!src) return false
  if (/openfreemap|gibs|openmaptiles|style/i.test(src)) return true
  return [cfg.streets, cfg.dark, cfg.satellite].some((u) => {
    try { return u && src.includes(new URL(u.replace(/[{}]/g, ''), location.href).host) } catch { return false }
  })
}
function resolvedBasemap() {
  if (fellBack.value) return 'simple'
  const choice = allowedBasemap(props.basemap, cfg)
  if (choice === 'auto') return props.theme === 'dark' && cfg.dark ? 'dark' : 'streets'
  return choice
}
function styleFor(kind) {
  const dark = props.theme === 'dark'
  if (kind === 'streets' && cfg.streets) return cfg.streets
  if (kind === 'dark' && cfg.dark) return cfg.dark
  if (kind === 'satellite' && cfg.satellite) return satelliteStyle()
  return simpleStyle(dark)
}

const fc = (features) => ({ type: 'FeatureCollection', features })
function pointData() {
  return fc(props.points.filter((p) => Number.isFinite(p.lon) && Number.isFinite(p.lat)).map((p) => ({
    type: 'Feature', id: undefined, geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
    properties: { id: String(p.id), color: p.color || '#507cba', title: p.title || '', sub: p.sub || '', size: p.size || 5, dim: p.dim ? 1 : 0, sel: p.selected ? 1 : 0, w: p.weight ?? 1, mix: String(p.mix ?? '') }
  })))
}
let arcPaths = []
function arcData() {
  arcPaths = props.arcs.map((a) => ({ path: greatCircle(a.from, a.to, 40), color: a.color || '#507cba', past: !!a.past }))
  return fc(arcPaths.map((a) => ({ type: 'Feature', geometry: { type: 'LineString', coordinates: a.path }, properties: { color: a.color, past: a.past ? 1 : 0 } })))
}
const pulseData = () => fc(props.pulses.map((p) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [p.lon, p.lat] }, properties: { color: p.color || '#d0558f' } })))

function addLayers() {
  if (!m) return
  const dark = props.theme === 'dark' || resolvedBasemap() === 'satellite' || resolvedBasemap() === 'dark'
  m.addSource('mm-arcs', { type: 'geojson', data: arcData() })
  m.addSource('mm-heads', { type: 'geojson', data: fc([]) })
  m.addSource('mm-pulses', { type: 'geojson', data: pulseData() })
  const data = pointData()
  m.addSource('mm-people', { type: 'geojson', data, ...(props.cluster ? { cluster: true, clusterRadius: 38, clusterMaxZoom: 5, clusterProperties: mixProperties() } : {}) })
  m.addSource('mm-heat-src', { type: 'geojson', data })
  m.addLayer({ id: 'mm-heat', type: 'heatmap', source: 'mm-heat-src', maxzoom: 9, layout: { visibility: props.heat ? 'visible' : 'none' },
    paint: { 'heatmap-weight': ['coalesce', ['get', 'w'], 1], 'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 0, 0.8, 9, 2.5],
      'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 0, 14, 9, 36], 'heatmap-opacity': 0.75,
      'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(0,0,0,0)', 0.2, '#2b6f8f', 0.45, '#2f8f5b', 0.7, '#e0b03a', 1, '#e0612f'] } })
  m.addLayer({ id: 'mm-arcs-past', type: 'line', source: 'mm-arcs', filter: ['==', ['get', 'past'], 1], layout: { 'line-cap': 'round' },
    paint: { 'line-color': ['get', 'color'], 'line-width': 0.8, 'line-opacity': 0.18 } })
  m.addLayer({ id: 'mm-arcs-now', type: 'line', source: 'mm-arcs', filter: ['==', ['get', 'past'], 0], layout: { 'line-cap': 'round' },
    paint: { 'line-color': ['get', 'color'], 'line-width': ['interpolate', ['linear'], ['zoom'], 1, 1.2, 8, 2.4], 'line-opacity': 0.7 } })
  m.addLayer({ id: 'mm-heads', type: 'circle', source: 'mm-heads', paint: { 'circle-radius': 3.2, 'circle-color': ['get', 'color'], 'circle-blur': 0.2, 'circle-stroke-width': 1, 'circle-stroke-color': dark ? '#0b0f12' : '#ffffff' } })
  m.addLayer({ id: 'mm-pulses', type: 'circle', source: 'mm-pulses', paint: { 'circle-radius': 6, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': ['get', 'color'], 'circle-stroke-width': 1.6, 'circle-stroke-opacity': 0.8 } })
  if (props.cluster) {
    // clusters are drawn as donut markers (see drawDonuts); this layer only keeps them out of the dot layer
    m.addLayer({ id: 'mm-clusters', type: 'circle', source: 'mm-people', filter: ['has', 'point_count'], paint: { 'circle-radius': 0, 'circle-opacity': 0 } })
  }
  m.addLayer({ id: 'mm-dots', type: 'circle', source: 'mm-people', filter: ['!', ['has', 'point_count']],
    paint: {
      'circle-color': ['get', 'color'],
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 1, ['case', ['==', ['get', 'sel'], 1], 8, ['*', ['get', 'size'], 0.8]], 10, ['case', ['==', ['get', 'sel'], 1], 12, ['*', ['get', 'size'], 1.6]]],
      'circle-opacity': ['case', ['==', ['get', 'dim'], 1], 0.35, 0.95],
      'circle-stroke-width': ['case', ['==', ['get', 'sel'], 1], 2.5, 1],
      'circle-stroke-color': ['case', ['==', ['get', 'sel'], 1], dark ? '#fff0be' : '#383168', dark ? 'rgba(10,14,18,.8)' : 'rgba(255,255,255,.9)']
    } })
}

function mixProperties() {
  const out = {}
  props.mixKeys.forEach((m, i) => { out[`m${i}`] = ['+', ['case', ['==', ['get', 'mix'], String(m.key)], 1, 0]] })
  return out
}
// cluster donuts: one small SVG per visible cluster, slices by the mix keys, the count in the middle
const markers = new Map()
let donutQueued = false
function donutSvg(p) {
  const total = p.point_count || 1, r = Math.min(30, 13 + Math.sqrt(total) * 1.1), ir = r * 0.62, size = r * 2
  let a0 = -Math.PI / 2, paths = ''
  props.mixKeys.forEach((m, i) => {
    const n = p[`m${i}`] || 0
    if (!n) return
    const a1 = a0 + (n / total) * Math.PI * 2, large = a1 - a0 > Math.PI ? 1 : 0
    const pt = (rad, a) => `${r + rad * Math.cos(a)},${r + rad * Math.sin(a)}`
    paths += n === total
      ? `<circle cx="${r}" cy="${r}" r="${(r + ir) / 2}" fill="none" stroke="${m.color}" stroke-width="${r - ir}"/>`
      : `<path d="M${pt(r, a0)}A${r},${r} 0 ${large} 1 ${pt(r, a1)}L${pt(ir, a1)}A${ir},${ir} 0 ${large} 0 ${pt(ir, a0)}Z" fill="${m.color}"/>`
    a0 = a1
  })
  if (!paths) paths = `<circle cx="${r}" cy="${r}" r="${(r + ir) / 2}" fill="none" stroke="#25785d" stroke-width="${r - ir}"/>`
  const label = total >= 1000 ? `${(total / 1000).toFixed(1)}k` : total
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">${paths}<circle cx="${r}" cy="${r}" r="${ir}" class="rwm-donut-hole"/><text x="${r}" y="${r}" text-anchor="middle" dominant-baseline="central">${label}</text></svg>`
}
function drawDonuts() {
  donutQueued = false
  if (!m || !props.cluster || !m.getSource('mm-people') || !m.isSourceLoaded('mm-people')) return
  const seen = new Set()
  for (const f of m.querySourceFeatures('mm-people')) {
    const p = f.properties
    if (!p?.cluster) continue
    const id = p.cluster_id
    if (seen.has(id)) continue
    seen.add(id)
    let mk = markers.get(id)
    if (!mk) {
      const node = document.createElement('button')
      node.type = 'button'
      node.className = 'rwm-donut'
      node.setAttribute('aria-label', `${p.point_count} people here; zoom in`)
      node.innerHTML = donutSvg(p)
      node.addEventListener('click', async (e) => {
        e.stopPropagation()
        const zoom = await m.getSource('mm-people').getClusterExpansionZoom(id)
        m.easeTo({ center: f.geometry.coordinates, zoom: Math.min(zoom, 9), duration: reduced ? 0 : 600 })
      })
      mk = new maplibre.Marker({ element: node }).setLngLat(f.geometry.coordinates).addTo(m)
      markers.set(id, mk)
    }
  }
  for (const [id, mk] of markers) if (!seen.has(id)) { mk.remove(); markers.delete(id) }
}
function clearDonuts() { for (const mk of markers.values()) mk.remove(); markers.clear() }
function queueDonuts() { if (!donutQueued) { donutQueued = true; requestAnimationFrame(drawDonuts) } }
const OUR_LAYERS = ['mm-heat', 'mm-arcs-past', 'mm-arcs-now', 'mm-heads', 'mm-pulses', 'mm-clusters', 'mm-cluster-n', 'mm-dots']
const OUR_SOURCES = ['mm-arcs', 'mm-heads', 'mm-pulses', 'mm-people', 'mm-heat-src']
function rebuild() {
  if (!m || !m.isStyleLoaded()) return
  clearDonuts()
  for (const l of OUR_LAYERS) if (m.getLayer(l)) m.removeLayer(l)
  for (const src of OUR_SOURCES) if (m.getSource(src)) m.removeSource(src)
  addLayers()
  setData()
}

function setData() {
  if (!m || !m.getSource('mm-people')) return
  const data = pointData()
  m.getSource('mm-people').setData(data)
  m.getSource('mm-heat-src')?.setData(data)
  clearDonuts()
  queueDonuts()
  m.getSource('mm-arcs').setData(arcData())
  m.getSource('mm-pulses').setData(pulseData())
  if (!fitted) fit()
}
function fit(animate = false) {
  const pts = props.points.filter((p) => Number.isFinite(p.lon) && Number.isFinite(p.lat))
  if (!m || !pts.length) return
  fitted = true
  const lons = pts.map((p) => p.lon), lats = pts.map((p) => p.lat)
  const b = [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]]
  const duration = animate && !reduced ? 900 : 0
  if (b[1][0] - b[0][0] < 2 && b[1][1] - b[0][1] < 2) m.easeTo({ center: [(b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2], zoom: 7, duration })
  else m.fitBounds(b, { padding: 50, maxZoom: 6, duration })
}

function animate(t) {
  raf = requestAnimationFrame(animate)
  if (!m || !m.getSource('mm-heads')) return
  const now = arcPaths.filter((a) => !a.past)
  if (now.length && !reduced) {
    const heads = now.map((a, i) => {
      const f = ((t / 2400) + i * 0.137) % 1
      const k = Math.min(a.path.length - 1, Math.floor(f * (a.path.length - 1)))
      return { type: 'Feature', geometry: { type: 'Point', coordinates: a.path[k] }, properties: { color: a.color } }
    })
    m.getSource('mm-heads').setData(fc(heads))
  }
  if (props.pulses.length && !reduced && m.getLayer('mm-pulses')) {
    const f = (t / 1600) % 1
    m.setPaintProperty('mm-pulses', 'circle-radius', 5 + f * 14)
    m.setPaintProperty('mm-pulses', 'circle-stroke-opacity', 0.9 * (1 - f))
  }
}

function applyProjection() {
  if (!m) return
  try { m.setProjection({ type: props.globe ? 'globe' : 'mercator' }) } catch { /* older engines: flat only */ }
}
function applyStyle() {
  if (!m) return
  const kind = resolvedBasemap()
  const key = `${kind}:${props.theme}`
  if (key === styleKey) return
  styleKey = key
  m.setStyle(styleFor(kind), { diff: false })
}

async function init() {
  cfg = await loadMapConfig()
  try {
    const [mod, worker] = await Promise.all([import('maplibre-gl'), import('maplibre-gl/dist/maplibre-gl-worker.mjs?url')])
    maplibre = mod.default || mod
    maplibre.setWorkerUrl?.(worker.default)
  } catch {
    failed.value = 'The map library could not load.'
    return
  }
  if (disposed || !el.value) return
  try {
    const kind = resolvedBasemap()
    styleKey = `${kind}:${props.theme}`
    m = new maplibre.Map({ container: el.value, style: styleFor(kind), center: [20, 20], zoom: 1.2, attributionControl: { compact: true },
      cooperativeGestures: false, dragRotate: true, maxPitch: 65, renderWorldCopies: !props.globe })
  } catch (err) {
    console.warn('Map could not start:', err?.message || err)
    failed.value = 'This browser cannot draw the map (WebGL is turned off). The list of people below still works.'
    return
  }
  map.value = m
  m.addControl(new maplibre.ScaleControl({ maxWidth: 90, unit: 'metric' }), 'bottom-right')
  m.on('rotate', () => { bearing.value = m.getBearing() })
  m.on('pitchend', () => { tilted.value = m.getPitch() > 5 })
  popup = new maplibre.Popup({ closeButton: false, closeOnClick: false, offset: 10, className: 'rwm-pop' })
  m.on('style.load', () => { clearDonuts(); applyProjection(); addLayers(); setData() })
  // street styles reference a few icons we do not need; give them a blank image instead of a console warning
  const blank = { width: 1, height: 1, data: new Uint8Array(4) }
  if (m.setMissingStyleImageResolver) m.setMissingStyleImageResolver((id) => { if (!m.hasImage(id)) m.addImage(id, blank) })
  else m.on('styleimagemissing', (e) => { if (!m.hasImage(e.id)) m.addImage(e.id, blank) })
  m.on('moveend', queueDonuts)
  m.on('sourcedata', (e) => { if (e.sourceId === 'mm-people' && e.isSourceLoaded) queueDonuts() })
  m.on('error', (e) => {
    // a street style that cannot load (offline, blocked, or the tile host is down) falls back to the offline map
    const src = String(e?.sourceId || e?.error?.url || e?.error?.message || '')
    if (!fellBack.value && resolvedBasemap() !== 'simple' && (!m.isStyleLoaded() || fromTileHost(src))) {
      fellBack.value = true
      emit('basemap-fallback')
      applyStyle()
    }
  })
  m.on('click', 'mm-dots', (e) => { const id = e.features?.[0]?.properties?.id; if (id) emit('select', id) })
  for (const layer of ['mm-dots']) {
    m.on('mouseenter', layer, () => { m.getCanvas().style.cursor = 'pointer' })
    m.on('mouseleave', layer, () => { m.getCanvas().style.cursor = ''; popup.remove() })
  }
  m.on('mousemove', 'mm-dots', (e) => {
    const p = e.features?.[0]?.properties
    if (!p) return
    const node = document.createElement('div')
    const b = document.createElement('b'); b.textContent = p.title; node.appendChild(b)
    if (p.sub) { const s = document.createElement('span'); s.textContent = p.sub; node.appendChild(s) }
    popup.setLngLat(e.lngLat).setDOMContent(node).addTo(m)
  })
  observer = new ResizeObserver(() => m?.resize())
  observer.observe(el.value)
  raf = requestAnimationFrame(animate)
}

function toggleTilt() {
  if (!m) return
  const on = m.getPitch() < 5
  m.easeTo({ pitch: on ? 55 : 0, bearing: on ? -15 : 0, duration: reduced ? 0 : 800 })
  tilted.value = on
}
function toggleFull() {
  if (document.fullscreenElement) document.exitFullscreen?.()
  else root.value?.requestFullscreen?.()
}
const onFull = () => { isFull.value = document.fullscreenElement === root.value; setTimeout(() => m?.resize(), 50) }

/** Fly to a place; used by the place list and the person picker. */
function flyTo(lon, lat, zoom = 6) { m?.flyTo({ center: [lon, lat], zoom, duration: reduced ? 0 : 1400, essential: true }) }
function fitAll() { fitted = false; fit(true) }
defineExpose({ flyTo, fit: fitAll })

watch(() => [props.points, props.arcs, props.pulses], setData)
watch(() => [props.basemap, props.theme], applyStyle)
watch(() => props.globe, () => { applyProjection(); m?.setRenderWorldCopies(!props.globe) })
watch(() => props.mixKeys.map((m) => m.key + m.color).join('|'), rebuild)
watch(() => props.heat, (v) => m?.getLayer('mm-heat') && m.setLayoutProperty('mm-heat', 'visibility', v ? 'visible' : 'none'))

onMounted(() => { init(); document.addEventListener('fullscreenchange', onFull) })
onBeforeUnmount(() => {
  disposed = true
  document.removeEventListener('fullscreenchange', onFull)
  cancelAnimationFrame(raf)
  observer?.disconnect()
  popup?.remove()
  clearDonuts()
  m?.remove()
  m = null
  map.value = null
})
</script>

<style scoped>
.rwm { position: relative; min-width: 0; }
.rwm-canvas { width: 100%; border: 1px solid var(--line); border-radius: 12px; overflow: hidden; background: var(--panel-2); }
.rwm-canvas:focus-visible { outline: 2px solid var(--accent, #25785d); outline-offset: 2px; }
.rwm.full { background: var(--panel); }
.rwm.full .rwm-canvas { height: 100vh !important; border-radius: 0; border: 0; }
.rwm-corner { position: absolute; left: 10px; bottom: 28px; z-index: 3; }
.rwm-ctrls { position: absolute; right: 10px; bottom: 44px; z-index: 3; display: grid; gap: 8px; justify-items: end; }
.rwm-ctrl-group { display: grid; background: var(--panel); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,.14); }
.rwm-ctrl-group button + button { border-top: 1px solid var(--line); }
.rwm-ctrl-group button, .rwm-ctrl { display: grid; place-items: center; width: 36px; height: 36px; border: 0; background: var(--panel); color: var(--text); cursor: pointer; }
.rwm-ctrl { border: 1px solid var(--line); border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,.14); }
.rwm-ctrl-group button:hover, .rwm-ctrl:hover { background: var(--panel-2); }
.rwm-ctrl[aria-pressed='true'] { color: var(--accent, #25785d); }
.rwm-ctrl-group button:focus-visible, .rwm-ctrl:focus-visible { outline: 2px solid var(--accent, #25785d); outline-offset: -2px; }
.rwm-3d { font-size: 11px; font-weight: 700; letter-spacing: .02em; }
.rwm :deep(.maplibregl-ctrl-scale) { background: color-mix(in srgb, var(--panel) 80%, transparent); color: var(--text); border-color: var(--muted); font-size: 10px; }
@media (max-width: 600px) { .rwm-ctrls { gap: 6px; } .rwm-ctrl-group button, .rwm-ctrl { width: 40px; height: 40px; } }
.rwm-overlay { position: absolute; top: 10px; left: 10px; z-index: 3; max-width: calc(100% - 70px); }
.rwm :deep(.rwm-donut) { border: 0; background: none; padding: 0; cursor: pointer; filter: drop-shadow(0 2px 6px rgba(0,0,0,.25)); }
.rwm :deep(.rwm-donut:focus-visible) { outline: 2px solid var(--accent, #25785d); outline-offset: 2px; border-radius: 50%; }
.rwm :deep(.rwm-donut text) { font: 600 11px/1 inherit; fill: #17181a; }
.rwm :deep(.rwm-donut-hole) { fill: #ffffff; }
.rwm.dark :deep(.rwm-donut text) { fill: #ececec; }
.rwm.dark :deep(.rwm-donut-hole) { fill: #1b1d21; }
.rwm-fail, .rwm-offline { position: absolute; left: 10px; bottom: 10px; margin: 0; max-width: calc(100% - 20px); font-size: 12px; padding: 6px 10px; border-radius: 8px; background: var(--panel); border: 1px solid var(--line); color: var(--muted); }
.rwm-fail { top: 50%; bottom: auto; transform: translateY(-50%); }
.rwm :deep(.rwm-pop .maplibregl-popup-content) { background: var(--panel, #fff); color: var(--text, #17181a); border: 1px solid var(--line); border-radius: 10px; padding: 7px 10px; font-size: 12px; box-shadow: 0 6px 20px rgba(0,0,0,.18); display: grid; gap: 2px; }
.rwm :deep(.rwm-pop .maplibregl-popup-content span) { color: var(--muted); font-size: 11px; }
.rwm :deep(.rwm-pop .maplibregl-popup-tip) { display: none; }
.rwm :deep(.maplibregl-ctrl-group) { background: var(--panel); border: 1px solid var(--line); box-shadow: none; }
.rwm.dark :deep(.maplibregl-ctrl-group button .maplibregl-ctrl-icon) { filter: invert(1); }
.rwm.dark :deep(.maplibregl-ctrl-attrib) { background: rgba(20,22,26,.75); color: #b0b3b8; }
.rwm.dark :deep(.maplibregl-ctrl-attrib a) { color: #d6d8db; }
</style>
