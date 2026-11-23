<template>
  <section class="persona-scene" aria-label="Interactive 3D simulated audience">
    <div class="persona-heading"><div><h3>Your simulated audience</h3><p>{{ people.length.toLocaleString() }} people · {{ segments.length }} segments</p></div><span v-if="isRunning" class="persona-status live">Updating</span></div>
    <div class="persona-controls">
      <label>View<select v-model="viewMode"><option value="world">World</option><option value="segments">Segments</option></select></label>
      <label>Find a person<input v-model="search" type="search" placeholder="Name, country or segment" /></label>
      <label>Person<select v-model="selectedId" @change="focusSelected"><option v-for="p in matchingPeople" :key="p.agent_id" :value="String(p.agent_id)">{{ p.name || `Person ${p.agent_id}` }}</option></select></label>
      <label v-if="rounds.length">Activity<select v-model="roundIndex"><option value="all">All recorded rounds</option><option v-for="(r, i) in rounds" :key="r.round_num ?? i" :value="String(i)">Round {{ r.round_num ?? i }} · {{ r.active_agents_count ?? r.active_agents?.length ?? 'unknown' }} active</option></select></label>
      <button class="ws-btn" @click="resetView">Reset view</button>
    </div>
    <div ref="host" :class="['persona-viewport', { failed: failure }]" role="img" :aria-label="sceneDescription">
      <p v-if="failure" class="persona-fallback">{{ failure }} Select a person above to inspect their saved profile and activity.</p>
      <p v-else-if="!people.length" class="persona-fallback">No persona profiles saved in this run.</p>
      <div v-if="!failure && people.length" class="persona-hint">Drag to orbit · Scroll to zoom · Select a person</div>
      <div v-if="hovered && !failure" class="persona-hover">{{ hovered.name || `Person ${hovered.agent_id}` }}<small>{{ [hovered.segment || 'Unspecified segment', hovered.country || 'Country unavailable'].join(' · ') }}</small></div>
    </div>
    <ul class="persona-legend" aria-label="Segment colors"><li v-for="(s, i) in segments" :key="s"><i :style="{ background: segmentColor(i) }" aria-hidden="true"></i>{{ s }}</li></ul>
    <details class="persona-map-notes">
      <summary>Map notes</summary>
      <p v-if="viewMode === 'world'">Simulated profiles appear near approximate country centers.<template v-if="unlocatedCount"> {{ unlocatedCount }} profiles with unknown locations appear beside the globe.</template></p>
      <p v-else>People are grouped by their assigned segment.</p>
      <p v-if="roundIndex !== 'all'">Bright markers were active in the selected round.</p>
      <p v-if="isRunning && checkedAt">Last checked {{ checkedAt }}.</p>
    </details>
    <AudiencePersonCard v-if="selected && showProfile" :person="selected" :color="segmentColor(segments.indexOf(selected.segment || 'Unspecified segment'))" :answer="selectedAnswer || null" :stats="selectedActivity || null" :thoughts="personThoughts" :edges="personEdges" :names="names" />
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { geoEquirectangular, geoPath } from 'd3'
import { countries, countryCenter, geographicPoint } from '../../workspace/audienceGeography'
import AudiencePersonCard from './AudiencePersonCard.vue'

const props = defineProps({ people: { type: Array, default: () => [] }, activity: { type: Array, default: () => [] }, timeline: { type: Array, default: () => [] }, responses: { type: Array, default: () => [] }, theme: { type: String, default: 'light' }, status: { type: String, default: '' }, checkedAt: { type: String, default: '' }, selectedPersonId: { type: String, default: '' }, thoughts: { type: Array, default: () => [] }, edges: { type: Array, default: () => [] }, names: { type: Object, default: () => ({}) }, showProfile: { type: Boolean, default: true } })
const emit = defineEmits(['select'])
const host = ref(null), failure = ref(''), selectedId = ref(props.selectedPersonId), hovered = ref(null), search = ref(''), roundIndex = ref('all'), viewMode = ref('world')
const unlocatedCount = computed(() => props.people.filter(person => !countryCenter(person.country)).length)
const segments = computed(() => [...new Set(props.people.map(p => p.segment || 'Unspecified segment'))])
const matchingPeople = computed(() => { const q = search.value.trim().toLowerCase(); return props.people.filter(p => `${p.name} ${p.country} ${p.segment}`.toLowerCase().includes(q)) })
const selected = computed(() => props.people.find(p => String(p.agent_id) === selectedId.value))
const selectedActivity = computed(() => props.activity.find(p => String(p.agent_id) === selectedId.value))
const selectedAnswer = computed(() => props.responses.find(p => String(p.agent_id) === selectedId.value)?.answer)
const rounds = computed(() => Array.isArray(props.timeline) ? props.timeline : [])
const isRunning = computed(() => /^(running|preparing|processing|in_progress)$/i.test(props.status))
// the plain-language card shows the survey answer itself, so the survey objection is not repeated as a thought
const personThoughts = computed(() => props.thoughts.filter(t => String(t.agent_id) === selectedId.value && t.text && !(selectedAnswer.value && t.source === 'survey')))
const personEdges = computed(() => props.edges.filter(e => String(e.from) === selectedId.value || String(e.to) === selectedId.value))
const sceneDescription = computed(() => `3D audience of ${props.people.length} simulated people ${viewMode.value === 'world' ? `placed at approximate saved country centers, with ${unlocatedCount.value} unlocated people separate from the globe` : `grouped into ${segments.value.length} segments`}. Select a person with the selector to read their profile. ${isRunning.value ? 'Data refreshes while the run is active.' : 'Showing recorded results.'}`)
const colors = ['#25785d', '#507cba', '#a76a40', '#9568aa', '#ab8834', '#278d99', '#b0606b', '#5e7f40']
const segmentColor = i => colors[i % colors.length]
let renderer, scene, camera, controls, group, resizeObserver, frame, ring, heads, bodies, pointerStart, contextLost = false
const positions = new Map(), pointer = new THREE.Vector2(), raycaster = new THREE.Raycaster()
const dummy = new THREE.Object3D()
let disposed = false, firstBuild = true, radius = 10, previousPeopleCount = 0
function disposeObject(object) {
  object.traverse(node => { node.geometry?.dispose(); const materials = Array.isArray(node.material) ? node.material : [node.material]; materials.filter(Boolean).forEach(material => { material.map?.dispose(); material.dispose() }) })
}
function worldTexture(dark) {
  const canvas = document.createElement('canvas'); canvas.width = 2048; canvas.height = 1024
  const ctx = canvas.getContext('2d'), projection = geoEquirectangular().scale(canvas.width / (2 * Math.PI)).translate([canvas.width / 2, canvas.height / 2])
  const path = geoPath(projection, ctx)
  ctx.fillStyle = dark ? '#162744' : '#e0eaf6'; ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.lineWidth = .7; ctx.strokeStyle = dark ? '#719b9870' : '#8aa4bd'
  for (const country of countries) { ctx.beginPath(); path(country); ctx.fillStyle = dark ? '#396775' : '#b1d2c8'; ctx.fill(); ctx.stroke() }
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace
  return texture
}
function buildWorld(dark) {
  const globeRadius = 7
  const globe = new THREE.Mesh(new THREE.SphereGeometry(globeRadius, 80, 48), new THREE.MeshStandardMaterial({ map: worldTexture(dark), roughness: .9, metalness: .05 }))
  group.add(globe)
  const halo = new THREE.Mesh(new THREE.SphereGeometry(globeRadius * 1.012, 48, 32), new THREE.MeshBasicMaterial({ color: dark ? '#87b8ff' : '#8cb6ec', side: THREE.BackSide, transparent: true, opacity: .17 })); group.add(halo)
  const unknown = props.people.filter(person => !countryCenter(person.country)), shelfColumns = Math.ceil(Math.sqrt(Math.max(1, unknown.length)))
  const shelfWidth = Math.max(2.4, shelfColumns * .37)
  if (unknown.length) {
    const shelf = new THREE.Mesh(new THREE.CircleGeometry(shelfWidth * .75, 48), new THREE.MeshBasicMaterial({ color: dark ? '#7b73a0' : '#a894ca', transparent: true, opacity: .14, side: THREE.DoubleSide })); shelf.rotation.x = -Math.PI / 2; shelf.position.set(10 + shelfWidth * .2, -2.8, 0); group.add(shelf)
    const canvas = document.createElement('canvas'); canvas.width = 512; canvas.height = 64; const ctx = canvas.getContext('2d'); ctx.fillStyle = dark ? '#d9deee' : '#55647e'; ctx.font = '24px sans-serif'; ctx.textAlign = 'center'; ctx.fillText(`Country unavailable · ${unknown.length}`, 256, 40)
    const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace
    const label = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthTest: false })); label.scale.set(4.3, .54, 1); label.position.set(10 + shelfWidth * .2, -3.4, 1); group.add(label)
  }
  bodies = new THREE.InstancedMesh(new THREE.CylinderGeometry(.075, .13, .32, 7), new THREE.MeshStandardMaterial({ roughness: .65 }), props.people.length)
  heads = new THREE.InstancedMesh(new THREE.SphereGeometry(.1, 8, 6), new THREE.MeshStandardMaterial({ roughness: .65 }), props.people.length)
  bodies.userData.personas = true; heads.userData.personas = true
  const selectedRound = roundIndex.value === 'all' ? null : rounds.value[Number(roundIndex.value)]
  const active = selectedRound ? new Set((selectedRound.active_agents || []).map(String)) : null
  const countryIndices = new Map()
  let unknownIndex = 0
  props.people.forEach((person, index) => {
    const center = countryCenter(person.country), normal = new THREE.Vector3(0, 1, 0), pos = new THREE.Vector3()
    if (center) {
      const key = center.join(','), local = countryIndices.get(key) || 0; countryIndices.set(key, local + 1)
      const base = new THREE.Vector3(...geographicPoint(...center, globeRadius)), tangent = new THREE.Vector3(0, 1, 0).cross(base).normalize(), bitangent = base.clone().normalize().cross(tangent).normalize()
      const angle = local * 2.39996323, distance = Math.min(1.25, Math.sqrt(local + .2) * .13)
      pos.copy(base).addScaledVector(tangent, Math.cos(angle) * distance).addScaledVector(bitangent, Math.sin(angle) * distance).normalize().multiplyScalar(globeRadius + .025); normal.copy(pos).normalize()
    } else {
      pos.set(10 + shelfWidth * .2 + ((unknownIndex % shelfColumns) - (shelfColumns - 1) / 2) * .37, -2.75, (Math.floor(unknownIndex / shelfColumns) - (shelfColumns - 1) / 2) * .37); unknownIndex++
    }
    positions.set(String(person.agent_id), { position: pos, normal, index, originalIndex: index })
    dummy.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), normal); dummy.scale.setScalar(1)
    dummy.position.copy(pos).addScaledVector(normal, .2); dummy.updateMatrix(); bodies.setMatrixAt(index, dummy.matrix)
    dummy.position.copy(pos).addScaledVector(normal, .47); dummy.updateMatrix(); heads.setMatrixAt(index, dummy.matrix)
    const segment = segments.value.indexOf(person.segment || 'Unspecified segment'), color = new THREE.Color(active && !active.has(String(person.agent_id)) ? (dark ? '#354754' : '#b4c3c9') : segmentColor(segment))
    bodies.setColorAt(index, color); heads.setColorAt(index, color)
  })
  group.add(bodies, heads)
  ring = new THREE.Mesh(new THREE.TorusGeometry(.23, .025, 6, 24), new THREE.MeshBasicMaterial({ color: dark ? '#fff0be' : '#383168' })); group.add(ring)
  radius = unknown.length ? Math.max(12, 10 + shelfWidth) : 8.3
  controls.maxPolarAngle = Math.PI
}
function build() {
  if (!scene || disposed) return
  if (!previousPeopleCount && props.people.length) firstBuild = true
  previousPeopleCount = props.people.length
  if (group) { scene.remove(group); disposeObject(group) }
  group = new THREE.Group(); scene.add(group); positions.clear()
  const dark = props.theme === 'dark'
  scene.background = new THREE.Color(dark ? '#141b20' : '#f3f7f6')
  if (viewMode.value === 'world') { buildWorld(dark); updateSelection(); if (firstBuild) { resetView(); firstBuild = false }; render(); return }
  controls.maxPolarAngle = Math.PI * .47
  const grouped = segments.value.map(segment => props.people.filter(p => (p.segment || 'Unspecified segment') === segment))
  const originalIndices = new Map(props.people.map((p, i) => [p, i]))
  const cols = Math.ceil(Math.sqrt(Math.max(1, grouped.length)))
  const maxSize = Math.max(1, ...grouped.map(p => p.length))
  const clusterRadius = Math.max(2.5, Math.sqrt(maxSize) * .53), spacing = clusterRadius * 2.5
  const rows = Math.ceil(grouped.length / cols)
  radius = Math.max(6, Math.sqrt(cols * cols + rows * rows) * spacing * .6)
  const bodyGeo = new THREE.CylinderGeometry(.12, .22, .53, 7), headGeo = new THREE.SphereGeometry(.16, 8, 6)
  bodies = new THREE.InstancedMesh(bodyGeo, new THREE.MeshStandardMaterial({ roughness: .6 }), props.people.length)
  heads = new THREE.InstancedMesh(headGeo, new THREE.MeshStandardMaterial({ roughness: .6 }), props.people.length)
  bodies.userData.personas = true; heads.userData.personas = true
  const selectedRound = roundIndex.value === 'all' ? null : rounds.value[Number(roundIndex.value)]
  const active = selectedRound ? new Set((selectedRound.active_agents || []).map(String)) : null
  let instance = 0
  for (let s = 0; s < grouped.length; s++) {
    const cx = ((s % cols) - (cols - 1) / 2) * spacing, cz = (Math.floor(s / cols) - (rows - 1) / 2) * spacing
    const floor = new THREE.Mesh(new THREE.CircleGeometry(clusterRadius + .6, 48), new THREE.MeshBasicMaterial({ color: segmentColor(s), transparent: true, opacity: dark ? .12 : .065, depthWrite: false }))
    floor.rotation.x = -Math.PI / 2; floor.position.set(cx, -.02, cz); group.add(floor)
    for (let j = 0; j < grouped[s].length; j++) {
      const p = grouped[s][j], angle = j * 2.39996323, distance = Math.sqrt(j + .5) * .5
      const pos = new THREE.Vector3(cx + Math.cos(angle) * distance, 0, cz + Math.sin(angle) * distance)
      const originalIndex = originalIndices.get(p)
      positions.set(String(p.agent_id), { position: pos, index: instance, originalIndex })
      dummy.position.copy(pos); dummy.position.y = .31; dummy.rotation.set(0, 0, 0); dummy.scale.setScalar(1); dummy.updateMatrix(); bodies.setMatrixAt(instance, dummy.matrix)
      dummy.position.y = .75; dummy.updateMatrix(); heads.setMatrixAt(instance, dummy.matrix)
      const c = new THREE.Color(active && !active.has(String(p.agent_id)) ? (dark ? '#344348' : '#cbd4d2') : segmentColor(s))
      bodies.setColorAt(instance, c); heads.setColorAt(instance, c); instance++
    }
  }
  group.add(bodies, heads)
  const ground = new THREE.GridHelper(radius * 2.4, 24, dark ? '#344047' : '#d9e3e0', dark ? '#242f34' : '#e6ece9'); ground.position.y = -.04; group.add(ground)
  ring = new THREE.Mesh(new THREE.TorusGeometry(.33, .035, 6, 24), new THREE.MeshBasicMaterial({ color: dark ? '#e5f4ef' : '#173d31' })); ring.rotation.x = -Math.PI / 2; group.add(ring)
  updateSelection()
  if (firstBuild) { resetView(); firstBuild = false }
  render()
}
function updateSelection() {
  const p = positions.get(selectedId.value)
  if (ring) { ring.visible = !!p; if (p) { const normal = p.normal || new THREE.Vector3(0, 1, 0); ring.position.copy(p.position).addScaledVector(normal, .04); ring.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal) } }
  render()
}
function render() { if (renderer && !disposed && !contextLost) renderer.render(scene, camera) }
function resetView() {
  if (!camera || !controls) return
  if (viewMode.value === 'world') {
    const fov = camera.fov * Math.PI / 180, horizontal = 2 * Math.atan(Math.tan(fov / 2) * camera.aspect), distance = radius / Math.sin(Math.min(fov, horizontal) / 2)
    const direction = new THREE.Vector3()
    for (const person of props.people) { const center = countryCenter(person.country); if (center) direction.add(new THREE.Vector3(...geographicPoint(...center))) }
    if (direction.lengthSq() < .001) { const known = props.people.find(person => countryCenter(person.country)); const center = known && countryCenter(known.country); direction.set(...(center ? geographicPoint(...center) : [.7, .25, 1])) }
    direction.normalize()
    // Face the saved audience on reset rather than hiding it behind the globe.
    controls.target.set(unlocatedCount.value ? 2.5 : 0, 0, 0); camera.position.copy(direction.multiplyScalar(distance)).add(controls.target)
  } else { camera.position.set(radius * .82, radius * .85, radius * .95); controls.target.set(0, 0, 0) }
  camera.near = .05; camera.far = radius * 20; camera.updateProjectionMatrix()
  controls.minDistance = 2; controls.maxDistance = radius * 6; controls.update(); render()
}
function focusSelected() {
  updateSelection()
  const person = positions.get(selectedId.value)
  if (viewMode.value === 'world' && person?.normal && camera && controls) {
    if (countryCenter(selected.value?.country)) { controls.target.set(0, 0, 0); camera.position.copy(person.normal).multiplyScalar(radius * 1.65) }
    else { controls.target.copy(person.position); camera.position.copy(person.position).add(new THREE.Vector3(3, 4, 5)) }
    controls.update(); render()
  }
}
function hit(event) {
  if (!renderer || !bodies || !heads) return null
  const r = renderer.domElement.getBoundingClientRect()
  pointer.set(((event.clientX - r.left) / r.width) * 2 - 1, -((event.clientY - r.top) / r.height) * 2 + 1)
  raycaster.setFromCamera(pointer, camera)
  const intersection = raycaster.intersectObjects([heads, bodies], false)[0]
  if (intersection?.instanceId == null) return null
  if (viewMode.value === 'world') { const globeHit = raycaster.intersectObjects(group.children.filter(object => object.geometry?.type === 'SphereGeometry' && object !== heads), false)[0]; if (globeHit && globeHit.distance < intersection.distance - .01) return null }
  const entry = [...positions.entries()].find(([, v]) => v.index === intersection.instanceId)
  return entry ? props.people[entry[1].originalIndex] : null
}
function move(event) { hovered.value = hit(event) }
function down(event) { pointerStart = { x: event.clientX, y: event.clientY } }
function up(event) {
  if (!pointerStart || Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) > 5) return
  const person = hit(event); if (person) selectedId.value = String(person.agent_id)
}
function leave() { hovered.value = null }
function lost(event) { event.preventDefault(); contextLost = true; failure.value = 'The 3D graphics connection was lost.' }
function restore() { contextLost = false; failure.value = ''; build() }
watch(matchingPeople, list => { if (!list.some(p => String(p.agent_id) === selectedId.value)) selectedId.value = list[0] ? String(list[0].agent_id) : '' }, { immediate: true })
watch(selectedId, value => { updateSelection(); emit('select', value) })
watch(() => props.selectedPersonId, value => { if (props.people.some(person => String(person.agent_id) === value)) selectedId.value = value })
watch(viewMode, () => { firstBuild = true })
const geometryKey = computed(() => JSON.stringify([props.people.map(p => [p.agent_id, p.segment, p.country]), viewMode.value, props.theme, roundIndex.value, roundIndex.value === 'all' ? null : rounds.value[Number(roundIndex.value)]?.active_agents]))
watch(geometryKey, async () => { await nextTick(); build() })
onMounted(() => {
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'low-power' }); renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); renderer.outputColorSpace = THREE.SRGBColorSpace
    scene = new THREE.Scene(); camera = new THREE.PerspectiveCamera(45, 1, .05, 1000)
    scene.add(new THREE.HemisphereLight('#ffffff', '#778c83', 2.5)); const light = new THREE.DirectionalLight('#ffffff', 2); light.position.set(7, 12, 8); scene.add(light)
    const canvas = renderer.domElement; canvas.setAttribute('aria-hidden', 'true'); host.value.appendChild(canvas)
    controls = new OrbitControls(camera, canvas); controls.enableDamping = !matchMedia('(prefers-reduced-motion: reduce)').matches; controls.dampingFactor = .12; controls.maxPolarAngle = Math.PI * .47; controls.addEventListener('change', render)
    canvas.addEventListener('pointermove', move); canvas.addEventListener('pointerdown', down); canvas.addEventListener('pointerup', up); canvas.addEventListener('pointerleave', leave); canvas.addEventListener('webglcontextlost', lost); canvas.addEventListener('webglcontextrestored', restore)
    resizeObserver = new ResizeObserver(() => { if (!host.value || disposed) return; const { width, height } = host.value.getBoundingClientRect(); if (!width || !height) return; renderer.setSize(width, height); camera.aspect = width / height; camera.updateProjectionMatrix(); render() }); resizeObserver.observe(host.value)
    build()
    function animate() { if (disposed) return; frame = requestAnimationFrame(animate); if (!document.hidden) controls.update() }
    animate()
  } catch { failure.value = 'This browser could not start 3D graphics.'; renderer?.dispose() }
})
onBeforeUnmount(() => {
  disposed = true; cancelAnimationFrame(frame); resizeObserver?.disconnect(); controls?.dispose()
  if (renderer) { const c = renderer.domElement; c.removeEventListener('pointermove', move); c.removeEventListener('pointerdown', down); c.removeEventListener('pointerup', up); c.removeEventListener('pointerleave', leave); c.removeEventListener('webglcontextlost', lost); c.removeEventListener('webglcontextrestored', restore); if (scene) disposeObject(scene); renderer.dispose(); c.remove() }
})
</script>
<style scoped>
.persona-scene {min-width:0}.persona-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.persona-heading h3{font-size:16px;font-weight:600;margin:0 0 5px}.persona-heading p,.persona-note{color:var(--muted);font-size:12px;line-height:1.65}.persona-status{white-space:nowrap;padding:4px 8px;border-radius:6px;font-size:11px;border:1px solid var(--line);background:var(--panel-2)}.persona-status.live{color:var(--accent);background:var(--accent-2)}.persona-controls{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.persona-controls label{display:flex;flex:1 1 130px;flex-direction:column;gap:5px;color:var(--muted);font-size:11px}.persona-controls input,.persona-controls select{width:100%;min-width:0;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--text);font-size:12px}.persona-controls button{align-self:end}.persona-viewport{height:360px;position:relative;overflow:hidden;border-radius:10px;background:var(--panel-2);border:1px solid var(--line)}.persona-viewport.failed :deep(canvas){display:none}.persona-viewport :deep(canvas){display:block;width:100%;height:100%;touch-action:none}.persona-hint{position:absolute;bottom:12px;left:12px;right:12px;z-index:1;font-size:11px;color:var(--muted);pointer-events:none}.persona-hover{position:absolute;top:12px;left:12px;right:12px;background:var(--panel);border:1px solid var(--line);padding:8px 10px;border-radius:6px;font-size:12px;pointer-events:none}.persona-hover small{display:block;color:var(--muted);margin-top:3px}.persona-fallback{padding:24px;color:var(--muted);font-size:13px;line-height:1.7;position:relative;z-index:2}.persona-legend{display:flex;flex-wrap:wrap;gap:8px 12px;margin:12px 0}.persona-legend span{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--muted)}.persona-legend i{width:8px;height:8px;border-radius:50%;display:inline-block}.persona-profile{margin-top:18px;padding-top:18px;border-top:1px solid var(--line)}.persona-profile header{display:flex;gap:10px;align-items:center;margin-bottom:16px}.persona-initial{display:grid;place-items:center;width:36px;height:36px;border-radius:10px;background:var(--accent-2);color:var(--accent);font-weight:600}.persona-profile h4{font-size:13px;margin:0 0 5px}.persona-profile header p,.persona-profile dl,.persona-answer p,.persona-profile details p,.persona-activity p{font-size:12px;color:var(--muted);line-height:1.7}.persona-profile dl{display:grid;grid-template-columns:95px minmax(0,1fr);gap:7px 10px}.persona-profile dt{color:var(--muted)}.persona-profile dd{margin:0;color:var(--text);overflow-wrap:anywhere}.persona-activity,.persona-answer{margin:18px 0}.persona-stats{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0;font-size:12px;color:var(--muted)}.persona-stats b{color:var(--text)}.persona-answer blockquote{margin:10px 0;padding-left:12px;border-left:2px solid var(--accent);color:var(--text);font-size:13px;line-height:1.8}.persona-profile details{font-size:12px;margin:14px 0}.persona-profile summary{cursor:pointer;margin-bottom:8px}@media(max-width:600px){.persona-viewport{height:300px}.persona-controls input,.persona-controls select{font-size:16px}.persona-profile dl{grid-template-columns:80px minmax(0,1fr)}}
</style>

<style scoped>
.persona-scene .persona-legend { list-style: none; margin: 10px 0 6px; padding: 0; display: flex; flex-wrap: wrap; gap: 5px 12px; }
.persona-legend li { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; line-height: 1.4; }
.persona-legend li i { width: 8px; height: 8px; flex: 0 0 8px; border-radius: 50%; }
.persona-map-notes { margin: 0 0 12px; color: var(--muted); font-size: 12px; }
.persona-map-notes summary { cursor: pointer; width: fit-content; }
</style>
