import { geoCentroid } from 'd3'
import topology from '../assets/geography/countries-110m.json'

// Decode the bundled quantized TopoJSON once. Countries come from Natural Earth,
// redistributed by world-atlas 2.0.2. Rendering never requests a remote map.
const decoded = topology.arcs.map(arc => {
  let x = 0, y = 0
  return arc.map(point => { x += point[0]; y += point[1]; return [x * topology.transform.scale[0] + topology.transform.translate[0], y * topology.transform.scale[1] + topology.transform.translate[1]] })
})
function ring(indices) {
  const points = []
  indices.forEach(index => { const arc = index < 0 ? [...decoded[~index]].reverse() : decoded[index]; points.push(...(points.length ? arc.slice(1) : arc)) })
  return points
}
export const countries = topology.objects.countries.geometries.map(geometry => ({
  type: 'Feature', id: geometry.id, properties: geometry.properties,
  geometry: { type: geometry.type, coordinates: geometry.type === 'Polygon' ? geometry.arcs.map(ring) : geometry.arcs.map(polygon => polygon.map(ring)) },
}))
const normalize = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '')
const centers = new Map(countries.map(country => [normalize(country.properties.name), geoCentroid(country)]))
const aliases = {
  us: 'United States of America', usa: 'United States of America', unitedstates: 'United States of America',
  uk: 'United Kingdom', greatbritain: 'United Kingdom', england: 'United Kingdom', scotland: 'United Kingdom', wales: 'United Kingdom',
  uae: 'United Arab Emirates', southkorea: 'South Korea', republicofkorea: 'South Korea', korea: 'South Korea',
  russianfederation: 'Russia', vietnam: 'Vietnam', czechrepublic: 'Czechia', ivorycoast: "Côte d'Ivoire",
  democraticrepublicofthecongo: 'Dem. Rep. Congo', drc: 'Dem. Rep. Congo', congo: 'Congo',
  dominicanrepublic: 'Dominican Rep.', southsudan: 'S. Sudan', centralafricanrepublic: 'Central African Rep.',
  palestine: 'Palestine', unitedrepublicoftanzania: 'Tanzania',
}
const englishRegions = new Intl.DisplayNames(['en'], { type: 'region' })
for (let a = 65; a <= 90; a++) for (let b = 65; b <= 90; b++) {
  const code = String.fromCharCode(a, b), name = englishRegions.of(code), normalized = normalize(name)
  if (centers.has(normalized)) aliases[code.toLowerCase()] = name
}
aliases.gb = 'United Kingdom'; aliases.us = 'United States of America'; aliases.kr = 'South Korea'
export function countryCenter(value) {
  const key = normalize(value)
  return centers.get(normalize(aliases[key] || value)) || null
}
export function geographicPoint(longitude, latitude, radius = 1) {
  const lat = latitude * Math.PI / 180, lon = longitude * Math.PI / 180
  return [radius * Math.cos(lat) * Math.cos(lon), radius * Math.sin(lat), -radius * Math.cos(lat) * Math.sin(lon)]
}
