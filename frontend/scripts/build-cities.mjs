// Builds public/geo/cities.json, the offline gazetteer the world map uses to put simulated people at their city.
// Source: the all-the-cities package (MIT), built from GeoNames (CC BY 4.0). Run: node scripts/build-cities.mjs
import { createRequire } from 'node:module'
import { writeFileSync } from 'node:fs'
const require = createRequire(import.meta.url)
const cities = require('all-the-cities')
const MIN_POPULATION = 5000
const byCountry = {}
for (const c of cities) {
  if (c.population < MIN_POPULATION) continue
  const [lon, lat] = c.loc.coordinates
  ;(byCountry[c.country] ||= []).push([c.name, Math.round(lat * 100) / 100, Math.round(lon * 100) / 100, Math.round(c.population / 1000)])
}
for (const list of Object.values(byCountry)) list.sort((a, b) => b[3] - a[3])
const out = { source: 'GeoNames via all-the-cities (CC BY 4.0)', min_population: MIN_POPULATION, fields: ['name', 'lat', 'lon', 'population_thousands'], countries: byCountry }
writeFileSync(new URL('../public/geo/cities.json', import.meta.url), JSON.stringify(out))
console.log('countries', Object.keys(byCountry).length, 'cities', Object.values(byCountry).reduce((n, l) => n + l.length, 0))
