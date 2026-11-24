// Where the map may load tiles from, set by the server (MM_MAP_TILES): the free OpenFreeMap and NASA hosts,
// your own tile server, or "off" (no outside requests: only the offline country map). Loaded once.
export const DEFAULT_MAP_CONFIG = {
  mode: 'openfreemap',
  streets: 'https://tiles.openfreemap.org/styles/liberty',
  dark: 'https://tiles.openfreemap.org/styles/dark',
  satellite: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg',
  satellite_attribution: 'NASA Blue Marble via GIBS',
  glyphs: 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf'
}

/** Which map types this server allows, in the order the switcher shows them. */
export function availableBasemaps(config) {
  const c = config || DEFAULT_MAP_CONFIG
  const out = []
  if (c.streets) out.push('auto')
  if (c.satellite) out.push('satellite')
  if (c.dark) out.push('dark')
  out.push('simple')
  return out
}

/** A saved choice that this server no longer allows falls back to the first one it does. */
export function allowedBasemap(choice, config) {
  const list = availableBasemaps(config)
  return list.includes(choice) ? choice : list[0]
}

let pending = null
export function loadMapConfig(url = `${import.meta.env?.BASE_URL || '/'}geo/map-config.json`) {
  if (!pending) {
    pending = fetch(url).then((r) => (r.ok ? r.json() : null)).then((d) => (d && d.mode ? d : DEFAULT_MAP_CONFIG)).catch(() => DEFAULT_MAP_CONFIG)
  }
  return pending
}
