// Where to put a simulated person on the flat world map: the centre of their saved country (Codex's bundled Natural
// Earth geography), spread a little so people in one country do not sit on one point. Cities are not geocoded.
import { countryCenter } from './audienceGeography'

/** "India, Mixed" or "India / Kenya": the first part that names a known country, as [lon, lat]. */
export function placeOfCountry(text) {
  if (!text) return null
  for (const part of String(text).split(/[,/;&]| and /i)) {
    const centre = countryCenter(part.trim())
    if (centre) return centre
  }
  return null
}

/** A stable spread around a country's centre (degrees), larger when more people share the country. */
export function spread([lon, lat], id, count) {
  const r = Math.min(4.5, 0.6 + Math.sqrt(Math.max(1, count)) * 0.35)
  let h = 2166136261
  for (const c of String(id)) h = Math.imul(h ^ c.charCodeAt(0), 16777619)
  const a = (((h >>> 0) % 3600) / 3600) * 2 * Math.PI
  const d = Math.sqrt((((h >>> 12) >>> 0) % 1000) / 1000) * r
  return [lon + Math.cos(a) * d, lat + Math.sin(a) * d * 0.8]
}

/** The segment colours the 3D audience uses, so both views agree. */
export const SEGMENT_COLORS = ['#25785d', '#507cba', '#a76a40', '#9568aa', '#ab8834', '#278d99', '#b0606b', '#5e7f40']
