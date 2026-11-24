<template>
  <div class="rwm" :class="{ dark: theme === 'dark' }">
    <div ref="el" class="rwm-canvas" :style="{ height: height + 'px' }" role="region" :aria-label="label" tabindex="0"></div>
    <p v-if="failed" class="rwm-fail" role="status">{{ failed }}</p>
    <p v-else-if="fellBack" class="rwm-offline" role="status">The street map could not load, so this is the offline map.</p>
  </div>
</template>

<script setup>
// A real, zoomable world map on MapLibre GL (BSD-3, open source). Street and dark styles come from OpenFreeMap
// (OpenStreetMap data, no key); satellite is NASA's Blue Marble (public domain); "Simple" is drawn from the bundled
// Natural Earth countries and works offline. People are points, interactions are great-circle arcs with a moving
// head, answers to the brand are pulsing rings, and an optional heat layer shows where weighted points cluster.
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import 'maplibre-gl/dist/maplibre-gl.css'
import { countries } from '../../workspace/audienceGeography'
import { greatCircle } from '../../workspace/cityPlace'

const props = defineProps({
  points: { type: Array, default: () => [] }, // { id, lon, lat, color, title, sub, size?, dim?, selected?, weight? }
  arcs: { type: Array, default: () => [] }, // { from:[lon,lat], to:[lon,lat], color, past? }
  pulses: { type: Array, default: () => [] }, // { lon, lat, color }
  basemap: { type: String, default: 'auto' }, // auto | streets | dark | satellite | simple
  globe: Boolean,
  heat: Boolean,
  cluster: Boolean,
  theme: { type: String, default: 'light' },
  height: { type: Number, default: 360 },
  label: { type: String, default: 'World map' }
})
const emit = defineEmits(['select', 'basemap-fallback'])
const el = ref(null), failed = ref(''), fellBack = ref(false)
let maplibre = null, map = null, popup = null, raf = 0, disposed = false, fitted = false, styleKey = '', observer = null
const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

const OFM = 'https://tiles.openfreemap.org/styles/'
function simpleStyle(dark) {
  return {
    version: 8,
    sources: { countries: { type: 'geojson', data: { type: 'FeatureCollection', features: countries }, attribution: 'Natural Earth' } },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': dark ? '#11171c' : '#eef3f6' } },
      { id: 'land', type: 'fill', source: 'countries', paint: { 'fill-color': dark ? '#1f2a33' : '#dfe8e3' } },
      { id: 'borders', type: 'line', source: 'countries', paint: { 'line-color': dark ? '#3a4a55' : '#b9c7bf', 'line-width': 0.6 } }
    ]
  }
}
function satelliteStyle() {
  return {
    version: 8,
    sources: {
      bm: { type: 'raster', tileSize: 256, maxzoom: 8, attribution: 'NASA Blue Marble via GIBS',
        tiles: ['https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg'] },
      countries: { type: 'geojson', data: { type: 'FeatureCollection', features: countries } }
    },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': '#05080c' } },
      { id: 'sat', type: 'raster', source: 'bm' },
      { id: 'borders', type: 'line', source: 'countries', paint: { 'line-color': 'rgba(255,255,255,.35)', 'line-width': 0.5 } }
    ]
  }
}
function resolvedBasemap() {
  if (fellBack.value) return 'simple'
  if (props.basemap === 'auto') return props.theme === 'dark' ? 'dark' : 'streets'
  return props.basemap
}
function styleFor(kind) {
  const dark = props.theme === 'dark'
  if (kind === 'streets') return OFM + 'liberty'
  if (kind === 'light') return OFM + 'positron'
  if (kind === 'dark') return OFM + 'dark'
  if (kind === 'satellite') return satelliteStyle()
  return simpleStyle(dark)
}

const fc = (features) => ({ type: 'FeatureCollection', features })
function pointData() {
  return fc(props.points.filter((p) => Number.isFinite(p.lon) && Number.isFinite(p.lat)).map((p) => ({
    type: 'Feature', id: undefined, geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
    properties: { id: String(p.id), color: p.color || '#507cba', title: p.title || '', sub: p.sub || '', size: p.size || 5, dim: p.dim ? 1 : 0, sel: p.selected ? 1 : 0, w: p.weight ?? 1 }
  })))
}
let arcPaths = []
function arcData() {
  arcPaths = props.arcs.map((a) => ({ path: greatCircle(a.from, a.to, 40), color: a.color || '#507cba', past: !!a.past }))
  return fc(arcPaths.map((a) => ({ type: 'Feature', geometry: { type: 'LineString', coordinates: a.path }, properties: { color: a.color, past: a.past ? 1 : 0 } })))
}
const pulseData = () => fc(props.pulses.map((p) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [p.lon, p.lat] }, properties: { color: p.color || '#d0558f' } })))

function addLayers() {
  if (!map) return
  const dark = props.theme === 'dark' || resolvedBasemap() === 'satellite' || resolvedBasemap() === 'dark'
  map.addSource('mm-arcs', { type: 'geojson', data: arcData() })
  map.addSource('mm-heads', { type: 'geojson', data: fc([]) })
  map.addSource('mm-pulses', { type: 'geojson', data: pulseData() })
  map.addSource('mm-people', { type: 'geojson', data: pointData(), ...(props.cluster ? { cluster: true, clusterRadius: 34, clusterMaxZoom: 5 } : {}) })
  map.addLayer({ id: 'mm-heat', type: 'heatmap', source: 'mm-people', maxzoom: 9, layout: { visibility: props.heat ? 'visible' : 'none' },
    paint: { 'heatmap-weight': ['coalesce', ['get', 'w'], 1], 'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 0, 0.8, 9, 2.5],
      'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 0, 14, 9, 36], 'heatmap-opacity': 0.75,
      'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(0,0,0,0)', 0.2, '#2b6f8f', 0.45, '#2f8f5b', 0.7, '#e0b03a', 1, '#e0612f'] } })
  map.addLayer({ id: 'mm-arcs-past', type: 'line', source: 'mm-arcs', filter: ['==', ['get', 'past'], 1], layout: { 'line-cap': 'round' },
    paint: { 'line-color': ['get', 'color'], 'line-width': 0.8, 'line-opacity': 0.18 } })
  map.addLayer({ id: 'mm-arcs-now', type: 'line', source: 'mm-arcs', filter: ['==', ['get', 'past'], 0], layout: { 'line-cap': 'round' },
    paint: { 'line-color': ['get', 'color'], 'line-width': ['interpolate', ['linear'], ['zoom'], 1, 1.2, 8, 2.4], 'line-opacity': 0.7 } })
  map.addLayer({ id: 'mm-heads', type: 'circle', source: 'mm-heads', paint: { 'circle-radius': 3.2, 'circle-color': ['get', 'color'], 'circle-blur': 0.2, 'circle-stroke-width': 1, 'circle-stroke-color': dark ? '#0b0f12' : '#ffffff' } })
  map.addLayer({ id: 'mm-pulses', type: 'circle', source: 'mm-pulses', paint: { 'circle-radius': 6, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': ['get', 'color'], 'circle-stroke-width': 1.6, 'circle-stroke-opacity': 0.8 } })
  if (props.cluster) {
    map.addLayer({ id: 'mm-clusters', type: 'circle', source: 'mm-people', filter: ['has', 'point_count'],
      paint: { 'circle-color': dark ? 'rgba(143,214,181,.85)' : 'rgba(37,120,93,.85)', 'circle-radius': ['interpolate', ['linear'], ['get', 'point_count'], 2, 11, 50, 20, 500, 30],
        'circle-stroke-width': 2, 'circle-stroke-color': dark ? '#0b0f12' : '#ffffff' } })
    if (map.getStyle()?.glyphs) map.addLayer({ id: 'mm-cluster-n', type: 'symbol', source: 'mm-people', filter: ['has', 'point_count'],
      layout: { 'text-field': ['get', 'point_count_abbreviated'], 'text-size': 11, 'text-font': ['Noto Sans Bold'] }, paint: { 'text-color': dark ? '#0b0f12' : '#ffffff' } })
  }
  map.addLayer({ id: 'mm-dots', type: 'circle', source: 'mm-people', filter: ['!', ['has', 'point_count']],
    paint: {
      'circle-color': ['get', 'color'],
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 1, ['case', ['==', ['get', 'sel'], 1], 8, ['*', ['get', 'size'], 0.8]], 10, ['case', ['==', ['get', 'sel'], 1], 12, ['*', ['get', 'size'], 1.6]]],
      'circle-opacity': ['case', ['==', ['get', 'dim'], 1], 0.35, 0.95],
      'circle-stroke-width': ['case', ['==', ['get', 'sel'], 1], 2.5, 1],
      'circle-stroke-color': ['case', ['==', ['get', 'sel'], 1], dark ? '#fff0be' : '#383168', dark ? 'rgba(10,14,18,.8)' : 'rgba(255,255,255,.9)']
    } })
}

function setData() {
  if (!map || !map.getSource('mm-people')) return
  map.getSource('mm-people').setData(pointData())
  map.getSource('mm-arcs').setData(arcData())
  map.getSource('mm-pulses').setData(pulseData())
  if (!fitted) fit()
}
function fit() {
  const pts = props.points.filter((p) => Number.isFinite(p.lon) && Number.isFinite(p.lat))
  if (!map || !pts.length) return
  fitted = true
  const lons = pts.map((p) => p.lon), lats = pts.map((p) => p.lat)
  const b = [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]]
  if (b[1][0] - b[0][0] < 2 && b[1][1] - b[0][1] < 2) map.jumpTo({ center: [(b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2], zoom: 7 })
  else map.fitBounds(b, { padding: 40, maxZoom: 6, duration: 0 })
}

function animate(t) {
  raf = requestAnimationFrame(animate)
  if (!map || !map.getSource('mm-heads')) return
  const now = arcPaths.filter((a) => !a.past)
  if (now.length && !reduced) {
    const heads = now.map((a, i) => {
      const f = ((t / 2400) + i * 0.137) % 1
      const k = Math.min(a.path.length - 1, Math.floor(f * (a.path.length - 1)))
      return { type: 'Feature', geometry: { type: 'Point', coordinates: a.path[k] }, properties: { color: a.color } }
    })
    map.getSource('mm-heads').setData(fc(heads))
  }
  if (props.pulses.length && !reduced && map.getLayer('mm-pulses')) {
    const f = (t / 1600) % 1
    map.setPaintProperty('mm-pulses', 'circle-radius', 5 + f * 14)
    map.setPaintProperty('mm-pulses', 'circle-stroke-opacity', 0.9 * (1 - f))
  }
}

function applyProjection() {
  if (!map) return
  try { map.setProjection({ type: props.globe ? 'globe' : 'mercator' }) } catch { /* older engines: flat only */ }
}
function applyStyle() {
  if (!map) return
  const kind = resolvedBasemap()
  const key = `${kind}:${props.theme}`
  if (key === styleKey) return
  styleKey = key
  map.setStyle(styleFor(kind), { diff: false })
}

async function init() {
  try {
    const mod = await import('maplibre-gl')
    maplibre = mod.default || mod
  } catch {
    failed.value = 'The map library could not load.'
    return
  }
  if (disposed || !el.value) return
  try {
    const kind = resolvedBasemap()
    styleKey = `${kind}:${props.theme}`
    map = new maplibre.Map({ container: el.value, style: styleFor(kind), center: [20, 20], zoom: 1.2, attributionControl: { compact: true },
      cooperativeGestures: false, dragRotate: false, maxPitch: 0, renderWorldCopies: !props.globe })
  } catch (err) {
    console.warn('Map could not start:', err?.message || err)
    failed.value = 'This browser cannot draw the map (WebGL is turned off). The list of people below still works.'
    return
  }
  map.addControl(new maplibre.NavigationControl({ showCompass: false }), 'top-right')
  map.addControl(new maplibre.FullscreenControl(), 'top-right')
  popup = new maplibre.Popup({ closeButton: false, closeOnClick: false, offset: 10, className: 'rwm-pop' })
  map.on('style.load', () => { applyProjection(); addLayers(); setData() })
  map.on('error', (e) => {
    // a street style that cannot load (offline, blocked, or the tile host is down) falls back to the offline map
    const src = String(e?.sourceId || e?.error?.url || e?.error?.message || '')
    if (!fellBack.value && resolvedBasemap() !== 'simple' && (!map.isStyleLoaded() || /openfreemap|gibs|openmaptiles|style/i.test(src))) {
      fellBack.value = true
      emit('basemap-fallback')
      applyStyle()
    }
  })
  map.on('click', 'mm-dots', (e) => { const id = e.features?.[0]?.properties?.id; if (id) emit('select', id) })
  map.on('click', 'mm-clusters', async (e) => {
    const f = e.features?.[0]
    if (!f) return
    const zoom = await map.getSource('mm-people').getClusterExpansionZoom(f.properties.cluster_id)
    map.easeTo({ center: f.geometry.coordinates, zoom })
  })
  for (const layer of ['mm-dots', 'mm-clusters']) {
    map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer' })
    map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; popup.remove() })
  }
  map.on('mousemove', 'mm-dots', (e) => {
    const p = e.features?.[0]?.properties
    if (!p) return
    const node = document.createElement('div')
    const b = document.createElement('b'); b.textContent = p.title; node.appendChild(b)
    if (p.sub) { const s = document.createElement('span'); s.textContent = p.sub; node.appendChild(s) }
    popup.setLngLat(e.lngLat).setDOMContent(node).addTo(map)
  })
  observer = new ResizeObserver(() => map?.resize())
  observer.observe(el.value)
  raf = requestAnimationFrame(animate)
}

/** Fly to a place; used by the place list and the person picker. */
function flyTo(lon, lat, zoom = 6) { map?.flyTo({ center: [lon, lat], zoom, duration: reduced ? 0 : 1400, essential: true }) }
defineExpose({ flyTo, fit: () => { fitted = false; fit() } })

watch(() => [props.points, props.arcs, props.pulses], setData)
watch(() => [props.basemap, props.theme], applyStyle)
watch(() => props.globe, () => { applyProjection(); map?.setRenderWorldCopies(!props.globe) })
watch(() => props.heat, (v) => map?.getLayer('mm-heat') && map.setLayoutProperty('mm-heat', 'visibility', v ? 'visible' : 'none'))

onMounted(init)
onBeforeUnmount(() => {
  disposed = true
  cancelAnimationFrame(raf)
  observer?.disconnect()
  popup?.remove()
  map?.remove()
  map = null
})
</script>

<style scoped>
.rwm { position: relative; min-width: 0; }
.rwm-canvas { width: 100%; border: 1px solid var(--line); border-radius: 12px; overflow: hidden; background: var(--panel-2); }
.rwm-canvas:focus-visible { outline: 2px solid var(--accent, #25785d); outline-offset: 2px; }
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
