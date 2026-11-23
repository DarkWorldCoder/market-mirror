// Parse local result exports without losing quoted commas, line breaks or duplicate columns.
export function parseCsv(text) {
  const rows = [], row = []; let field = '', quoted = false
  text = String(text).replace(/^\uFEFF/, '')
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (c === '"') {
      if (quoted && text[i + 1] === '"') { field += '"'; i++ }
      else quoted = !quoted
    } else if (!quoted && (c === ',' || c === '\n' || c === '\r')) {
      row.push(field); field = ''
      if (c !== ',') { rows.push(row.splice(0)); if (c === '\r' && text[i + 1] === '\n') i++ }
    } else field += c
  }
  if (quoted) throw new Error('The CSV ends inside a quoted field. Download it to inspect the original export.')
  if (field || row.length) { row.push(field); rows.push(row) }
  const sourceHeaders = rows.shift() || [], width = Math.max(sourceHeaders.length, ...rows.map(r => r.length), 0)
  const seen = new Set()
  const headers = Array.from({ length: width }, (_, i) => {
    const original = sourceHeaders[i] || `Column ${i + 1}`
    let key = original, suffix = 2
    while (seen.has(key)) key = `${original} (${suffix++})`
    seen.add(key); return key
  })
  return rows.filter(r => r.some(Boolean)).map(r => Object.fromEntries(headers.map((h, i) => {
    const v = r[i] ?? '', numeric = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(v.trim())
    return [h, numeric && Number.isFinite(Number(v)) ? Number(v) : v]
  })))
}
