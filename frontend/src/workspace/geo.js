// Real world geography for the map view: Natural Earth country shapes (world-atlas 110m, public domain data,
// ISC package), converted with topojson-client, and each country's centroid from d3-geo. People are placed in their
// country; cities are not geocoded, so points inside a country are spread around its centre for visibility.
import { feature } from 'topojson-client'
import { geoCentroid } from 'd3'

let cache = null

const ALIASES = {
  usa: 'United States of America', us: 'United States of America', 'united states': 'United States of America', america: 'United States of America',
  uk: 'United Kingdom', 'great britain': 'United Kingdom', britain: 'United Kingdom', england: 'United Kingdom', scotland: 'United Kingdom', wales: 'United Kingdom',
  uae: 'United Arab Emirates', 'south korea': 'South Korea', korea: 'South Korea', 'north korea': 'North Korea', drc: 'Dem. Rep. Congo',
  'democratic republic of the congo': 'Dem. Rep. Congo', 'ivory coast': "Côte d'Ivoire", "cote d'ivoire": "Côte d'Ivoire", czech: 'Czechia',
  'czech republic': 'Czechia', 'bosnia and herzegovina': 'Bosnia and Herz.', 'dominican republic': 'Dominican Rep.', 'north macedonia': 'Macedonia',
  eswatini: 'eSwatini', swaziland: 'eSwatini', 'south sudan': 'S. Sudan', 'central african republic': 'Central African Rep.', russia: 'Russia',
  'russian federation': 'Russia', vietnam: 'Vietnam', 'viet nam': 'Vietnam', burma: 'Myanmar', holland: 'Netherlands', 'the netherlands': 'Netherlands'
}

/** {geojson, centroid(name) -> [lon, lat] | null, match(countryText) -> canonical name | null}, loaded once. */
export async function worldGeo() {
  if (cache) return cache
  const topo = (await import('world-atlas/countries-110m.json')).default
  const geojson = feature(topo, topo.objects.countries)
  // ECharts matches regions by properties.name
  for (const f of geojson.features) f.properties = { name: f.properties.name }
  const byLower = new Map(geojson.features.map((f) => [f.properties.name.toLowerCase(), f]))
  const centres = new Map()
  const match = (text) => {
    if (!text) return null
    // "India, Mixed" or "India / Kenya": take the first part that names a real country
    for (const part of String(text).split(/[,/;&]| and /i)) {
      const k = part.trim().toLowerCase()
      if (!k) continue
      const name = byLower.get(k)?.properties.name || ALIASES[k]
      if (name && byLower.has(name.toLowerCase())) return name
    }
    return null
  }
  const centroid = (name) => {
    if (!name) return null
    if (!centres.has(name)) {
      const f = byLower.get(name.toLowerCase())
      centres.set(name, f ? geoCentroid(f) : null)
    }
    return centres.get(name)
  }
  cache = { geojson, match, centroid }
  return cache
}

/** A stable spread around a country's centre, so people in one country do not sit on one pixel. */
export function spread([lon, lat], id, count) {
  const n = Math.max(1, count)
  const r = Math.min(4.5, 0.6 + Math.sqrt(n) * 0.35) // degrees
  let h = 2166136261
  for (const c of String(id)) h = Math.imul(h ^ c.charCodeAt(0), 16777619)
  const a = ((h >>> 0) % 3600) / 3600 * 2 * Math.PI
  const d = Math.sqrt((((h >>> 12) >>> 0) % 1000) / 1000) * r
  return [lon + Math.cos(a) * d, lat + Math.sin(a) * d * 0.8]
}
