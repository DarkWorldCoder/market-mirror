// Where a simulated person sits on the real world map: their saved city, looked up in an offline gazetteer
// (public/geo/cities.json, GeoNames via all-the-cities, towns of 5,000+ people). If the city is not found the person
// goes to their country's centre and is marked approximate. Pure functions; loadGazetteer fetches the file once.

const strip = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim()

// Renamed or commonly written another way; GeoNames keeps the left-hand spelling's partner.
const CITY_ALIASES = {
  gurugram: 'gurgaon', bengaluru: 'bangalore', bombay: 'mumbai', calcutta: 'kolkata', madras: 'chennai', 'new york city': 'new york',
  nyc: 'new york', 'washington dc': 'washington', 'washington d c': 'washington', sf: 'san francisco', la: 'los angeles',
  saigon: 'ho chi minh city', 'mexico city': 'mexico city', 'ciudad de mexico': 'mexico city', peking: 'beijing', kiev: 'kyiv',
  'st petersburg': 'saint petersburg', prayagraj: 'allahabad', mysuru: 'mysore', kochi: 'cochin', hubballi: 'hubli',
  chattogram: 'chittagong', chitwan: 'bharatpur', legazpi: 'legaspi', belagavi: 'belgaum', mangaluru: 'mangalore', kalaburagi: 'gulbarga',
  vadodara: 'vadodara', thiruvananthapuram: 'thiruvananthapuram', trivandrum: 'thiruvananthapuram', kozhikode: 'calicut', puducherry: 'pondicherry'
}

const COUNTRY_ALIASES = {
  usa: 'US', us: 'US', 'united states of america': 'US', america: 'US', uk: 'GB', 'great britain': 'GB', britain: 'GB', england: 'GB',
  scotland: 'GB', wales: 'GB', 'northern ireland': 'GB', uae: 'AE', 'south korea': 'KR', korea: 'KR', 'north korea': 'KP', russia: 'RU',
  vietnam: 'VN', 'viet nam': 'VN', 'czech republic': 'CZ', czechia: 'CZ', 'ivory coast': 'CI', "cote d ivoire": 'CI', turkey: 'TR',
  turkiye: 'TR', 'hong kong': 'HK', taiwan: 'TW', iran: 'IR', syria: 'SY', laos: 'LA', bolivia: 'BO', venezuela: 'VE', tanzania: 'TZ',
  moldova: 'MD', 'drc': 'CD', 'dr congo': 'CD', 'democratic republic of the congo': 'CD', 'republic of the congo': 'CG', palestine: 'PS',
  myanmar: 'MM', burma: 'MM', eswatini: 'SZ', swaziland: 'SZ', 'cape verde': 'CV', macedonia: 'MK', 'north macedonia': 'MK'
}

let countryCodes = null
/** "India" / "USA" / "in" -> "IN". */
export function countryCode(text) {
  const n = strip(text)
  if (!n) return null
  if (COUNTRY_ALIASES[n]) return COUNTRY_ALIASES[n]
  if (!countryCodes) {
    countryCodes = new Map()
    let names = null
    try { names = new Intl.DisplayNames(['en'], { type: 'region' }) } catch { names = null }
    for (let a = 65; a <= 90; a++) for (let b = 65; b <= 90; b++) {
      const code = String.fromCharCode(a, b)
      let name = null
      try { name = names?.of(code) } catch { name = null }
      if (name && name !== code) countryCodes.set(strip(name), code)
    }
  }
  if (countryCodes.has(n)) return countryCodes.get(n)
  if (/^[a-z]{2}$/.test(n)) {
    const up = n.toUpperCase()
    for (const code of countryCodes.values()) if (code === up) return up
  }
  return null
}

/** The first part of "India, Mixed" or "India / Kenya" that names a country. */
export function countryCodeOf(text) {
  for (const part of String(text || '').split(/[,/;&]| and /i)) {
    const c = countryCode(part.trim())
    if (c) return c
  }
  return null
}

/** Index the gazetteer: { CC: Map(normalized name -> [lon, lat, popK, name]) }. */
export function indexGazetteer(data) {
  const out = {}
  for (const [cc, list] of Object.entries(data?.countries || {})) {
    const m = new Map()
    for (const [name, lat, lon, pop] of list) {
      const key = strip(name)
      const value = [lon, lat, pop, name]
      // lists are sorted by population, so the first city with a key is the biggest
      for (const k of [key, key.replace(/ /g, ''), key.replace(/^city of | city$/g, '')]) if (k && !m.has(k)) m.set(k, value)
    }
    out[cc] = m
  }
  return out
}

/** [lon, lat, cityName] for a city in a country, or null. Tries the full name, aliases, then each comma part. */
export function findCity(index, city, country) {
  if (!city || city === 'null') return null
  const cc = countryCodeOf(country)
  // no usable country: look in every country (biggest match wins, since each pool is sorted by population)
  const pools = cc && index[cc] ? [index[cc]] : cc ? [] : Object.values(index)
  if (!pools.length) return null
  const tries = []
  const add = (s) => {
    const k = strip(s).replace(/ (town|city|village|barangay|district|suburbs?)$/g, '').replace(/^(a |the )?(barangay|town|village|suburb) (in|of|near) /, '')
    for (const t of [k, CITY_ALIASES[k], k.replace(/ /g, '')]) if (t && !tries.includes(t)) tries.push(t)
  }
  add(city)
  for (const part of String(city || '').split(/[,(/]| - /)) add(part)
  for (const key of tries) {
    let best = null
    for (const pool of pools) {
      const hit = pool.get(key)
      if (hit && (!best || hit[2] > best[2])) best = hit
    }
    if (best) return [best[0], best[1], best[3]]
  }
  if (pools.length > 1) return null
  // "Greater Nairobi", "Nairobi suburbs": a known city name inside the text, biggest first
  const text = ` ${strip(city)} `
  for (const pool of pools) {
    for (const [key, hit] of pool) {
      if (key.length >= 4 && text.includes(` ${key} `)) return [hit[0], hit[1], hit[3]]
    }
  }
  return null
}

let gazetteer = null
/** Fetch and index public/geo/cities.json once. Resolves to null when it cannot be loaded. */
export function loadGazetteer(url = `${import.meta.env?.BASE_URL || '/'}geo/cities.json`) {
  if (!gazetteer) {
    gazetteer = fetch(url).then((r) => (r.ok ? r.json() : null)).then((d) => (d ? indexGazetteer(d) : null)).catch(() => null)
  }
  return gazetteer
}

/** A small stable offset (degrees) so people in one city do not sit on one point; wider when more share it. */
export function jitter([lon, lat], id, count, wide = false) {
  const r = wide ? Math.min(4, 0.5 + Math.sqrt(Math.max(1, count)) * 0.3) : Math.min(0.12, 0.015 + Math.sqrt(Math.max(1, count)) * 0.012)
  let h = 2166136261
  for (const c of String(id)) h = Math.imul(h ^ c.charCodeAt(0), 16777619)
  const a = (((h >>> 0) % 3600) / 3600) * 2 * Math.PI
  const d = Math.sqrt((((h >>> 12) >>> 0) % 1000) / 1000) * r
  return [lon + Math.cos(a) * d, lat + Math.sin(a) * d * 0.8]
}

/** Points along the great circle from a to b ([lon, lat]), for arcs that curve the way flights do. */
export function greatCircle(a, b, steps = 48) {
  const rad = Math.PI / 180
  const [l1, p1] = [a[0] * rad, a[1] * rad]
  const [l2, p2] = [b[0] * rad, b[1] * rad]
  const d = 2 * Math.asin(Math.sqrt(Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin((l2 - l1) / 2) ** 2))
  if (!d) return [a, b]
  const out = []
  for (let i = 0; i <= steps; i++) {
    const f = i / steps
    const A = Math.sin((1 - f) * d) / Math.sin(d)
    const B = Math.sin(f * d) / Math.sin(d)
    const x = A * Math.cos(p1) * Math.cos(l1) + B * Math.cos(p2) * Math.cos(l2)
    const y = A * Math.cos(p1) * Math.sin(l1) + B * Math.cos(p2) * Math.sin(l2)
    const z = A * Math.sin(p1) + B * Math.sin(p2)
    out.push([Math.atan2(y, x) / rad, Math.atan2(z, Math.sqrt(x * x + y * y)) / rad])
  }
  // keep the line continuous across the antimeridian
  for (let i = 1; i < out.length; i++) {
    while (out[i][0] - out[i - 1][0] > 180) out[i][0] -= 360
    while (out[i][0] - out[i - 1][0] < -180) out[i][0] += 360
  }
  return out
}
