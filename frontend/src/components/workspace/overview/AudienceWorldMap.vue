<template>
  <section v-if="cityRows.length || countryRows.length" class="awm" aria-labelledby="awm-heading">
    <div class="overview-section-title">
      <div>
        <h2 id="awm-heading">Where your simulated buyers live</h2>
        <p>{{ number(totalPeople) }} simulated people across {{ geography.runs_with_places || 'your' }} experiments, at the cities saved in their profiles.</p>
      </div>
      <div class="awm-tools">
        <div v-if="basemapList.length > 1" class="wfm-seg" role="group" aria-label="Map style">
          <button v-for="b in basemapList" :key="b.id" type="button" :aria-pressed="basemap === b.id" @click="basemap = b.id">{{ b.label }}</button>
        </div>
        <button type="button" class="wfm-chip" :aria-pressed="globe" @click="globe = !globe"><Globe2 :size="13" aria-hidden="true" />Globe</button>
      </div>
    </div>
    <div class="awm-body">
      <RealWorldMap ref="mapRef" :points="points" :basemap="basemap" :globe="globe" :theme="theme" :height="340"
        :label="`World map of ${number(totalPeople)} simulated people by city`" />
      <ol class="awm-list" aria-label="Places with the most simulated people">
        <li v-for="pl in top" :key="pl.key">
          <button type="button" @click="pl.at && mapRef?.flyTo(pl.at[0], pl.at[1], pl.city ? 7 : 4)" :disabled="!pl.at">
            <span class="awm-name">{{ pl.label }}</span>
            <span class="awm-bar" aria-hidden="true"><i :style="{ width: Math.max(4, Math.round(100 * pl.people / maxPeople)) + '%' }"></i></span>
            <small>{{ number(pl.people) }} people · {{ pl.runs }} {{ pl.runs === 1 ? 'run' : 'runs' }}</small>
          </button>
        </li>
      </ol>
    </div>
    <p class="awm-note">Simulated people, not real customers. Towns of 5,000+ people come from GeoNames; places not found sit at the country's centre. People shared by several runs are counted once per run.</p>
  </section>
</template>

<script setup>
// Every simulated person across all saved runs, grouped by city, on the real world map.
import { computed, onMounted, ref, watch } from 'vue'
import { Globe2 } from 'lucide-vue-next'
import RealWorldMap from '../RealWorldMap.vue'
import { placeOfCountry } from '../../../workspace/geoPlace'
import { findCity, loadGazetteer } from '../../../workspace/cityPlace'
import { availableBasemaps, loadMapConfig } from '../../../workspace/mapConfig'

const props = defineProps({ geography: { type: Object, default: () => ({}) }, theme: { type: String, default: 'light' } })
const mapRef = ref(null), gazetteer = ref(null)
const pref = (k, d) => { try { return localStorage.getItem(k) || d } catch { return d } }
const basemap = ref(pref('mm-map-style', 'auto')), globe = ref(pref('mm-map-globe', '') === '1')
watch(basemap, (v) => { try { localStorage.setItem('mm-map-style', v) } catch { /* private window */ } })
watch(globe, (v) => { try { localStorage.setItem('mm-map-globe', v ? '1' : '') } catch { /* private window */ } })
const basemaps = [{ id: 'auto', label: 'Streets' }, { id: 'satellite', label: 'Satellite' }, { id: 'simple', label: 'Simple' }]
const mapCfg = ref(null)
const basemapList = computed(() => { const ok = availableBasemaps(mapCfg.value || undefined); return basemaps.filter((b) => ok.includes(b.id)) })
const number = (n) => Number(n || 0).toLocaleString()

const cityRows = computed(() => props.geography?.cities || [])
const countryRows = computed(() => props.geography?.countries || [])
const totalPeople = computed(() => countryRows.value.reduce((n, c) => n + (c.people || 0), 0) || cityRows.value.reduce((n, c) => n + (c.people || 0), 0))

// cities found in the gazetteer, plus whatever is left of each country at its centre
const places = computed(() => {
  const idx = gazetteer.value, out = [], placedByCountry = {}
  for (const c of cityRows.value) {
    const hit = idx ? findCity(idx, c.city, c.country) : null
    if (!hit) continue
    out.push({ key: `c:${c.country}:${c.city}`, label: `${hit[2]}, ${c.country}`, city: hit[2], at: [hit[0], hit[1]], people: c.people, runs: c.runs || 1 })
    placedByCountry[c.country] = (placedByCountry[c.country] || 0) + c.people
  }
  for (const c of countryRows.value) {
    const rest = (c.people || 0) - (placedByCountry[c.country] || 0)
    const at = placeOfCountry(c.country)
    if (rest > 0) out.push({ key: `k:${c.country}`, label: `${c.country} (city not given)`, city: '', at, people: rest, runs: c.runs || 1 })
  }
  return out.sort((a, b) => b.people - a.people)
})
const top = computed(() => places.value.slice(0, 8))
const maxPeople = computed(() => Math.max(1, ...places.value.map((p) => p.people)))
const points = computed(() => places.value.filter((p) => p.at).map((p) => ({
  id: p.key, lon: p.at[0], lat: p.at[1], color: p.city ? '#25785d' : '#8a8f94', title: p.label,
  sub: `${number(p.people)} simulated people · ${p.runs} ${p.runs === 1 ? 'run' : 'runs'}`, size: Math.min(22, 4 + Math.sqrt(p.people) * 1.1)
})))

onMounted(async () => { loadMapConfig().then((c) => { mapCfg.value = c }); gazetteer.value = await loadGazetteer() })
</script>

<style scoped>
.awm { border: 1px solid var(--line); border-radius: 14px; padding: 16px; background: var(--panel); margin: 0 0 16px; min-width: 0; }
.awm .overview-section-title { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px; align-items: flex-start; }
.awm-tools { display: flex; gap: 6px; flex-wrap: wrap; }
.awm-body { display: grid; gap: 12px; margin-top: 12px; }
@media (min-width: 900px) { .awm-body { grid-template-columns: minmax(0, 1fr) 260px; } }
.awm-list { list-style: none; margin: 0; padding: 0 2px 0 0; display: grid; gap: 6px; align-content: start; max-height: 340px; overflow-y: auto; }
.awm-list button { width: 100%; display: grid; gap: 3px; text-align: left; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--text); font: inherit; font-size: 12.5px; padding: 8px 10px; cursor: pointer; }
.awm-list button:hover:not(:disabled) { background: var(--panel-2); }
.awm-list button:focus-visible { outline: 2px solid var(--accent, #25785d); outline-offset: 1px; }
.awm-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.awm-bar { height: 4px; border-radius: 4px; background: var(--line); overflow: hidden; }
.awm-bar i { display: block; height: 100%; background: var(--data, #5b6470); }
.awm-list small { color: var(--muted); font-size: 11px; }
.awm-note { margin: 10px 0 0; font-size: 11.5px; color: var(--muted); }
.wfm-seg { display: inline-flex; border: 1px solid var(--line); border-radius: 9px; overflow: hidden; background: var(--panel); }
.wfm-seg button, .wfm-chip { display: inline-flex; align-items: center; gap: 5px; border: 0; background: none; color: var(--text); font: inherit; font-size: 11.5px; padding: 5px 9px; cursor: pointer; }
.wfm-seg button + button { border-left: 1px solid var(--line); }
.wfm-seg button[aria-pressed='true'], .wfm-chip[aria-pressed='true'] { background: var(--panel-2); font-weight: 600; box-shadow: inset 0 -2px 0 var(--accent, #25785d); }
.wfm-chip { border: 1px solid var(--line); border-radius: 9px; background: var(--panel); }
</style>
