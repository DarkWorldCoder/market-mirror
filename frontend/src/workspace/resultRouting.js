export const reportTitle = file => String(file).replace(/\.(json|md|csv|html)$/i, '').replaceAll('_', ' ').replaceAll('-', ' ').replace(/\b\w/, c => c.toUpperCase())
const normalized = value => String(value).toLowerCase().replace(/\.(json|md|csv|html)\b/g, '').replace(/[^a-z0-9]+/g, ' ').trim()
export function funnelRows(value) {
  return (Array.isArray(value) ? value : []).map(row => Array.isArray(row) ? { label: row[0], n: row[1] } : row).filter(row => row && Number.isFinite(row.n))
}
export function pricingText(pricing, currency = '') {
  if (!pricing || typeof pricing !== 'object') return ''
  const amount = value => Number.isFinite(value) ? `${currency ? `${currency} ` : ''}${Number(value.toFixed(2))}` : null
  const fields = [['acceptable_low', 'Acceptable low'], ['acceptable_high', 'Acceptable high'], ['optimal', 'Optimal']]
  const values = fields.filter(([key]) => amount(pricing[key]) !== null).map(([key, label]) => `${label}: ${amount(pricing[key])}`)
  if (Number.isFinite(pricing.median)) values.push(`Median: ${amount(pricing.median)}`)
  else if (pricing.median && typeof pricing.median === 'object') {
    for (const [key, value] of Object.entries(pricing.median)) if (amount(value) !== null) values.push(`Median ${key.replace(/^price_/, '').replaceAll('_', ' ')}: ${amount(value)}`)
  }
  return values.join(' · ')
}
// Resolve a read-only report reference. Contents are fetched by the chat attachment, never persisted in chat history.
export function savedReportFor(query, files, summary) {
  const q = normalized(query), available = Array.isArray(files) ? files : []
  const explicit = available.filter(file => String(query).toLowerCase().includes(file.toLowerCase())).sort((a,b) => b.length-a.length)
  if (explicit.length) return { file: explicit[0], path: [], title: reportTitle(explicit[0]) }
  const exact = available.filter(file => { const title = normalized(file); return title.length > 3 && (` ${q} `).includes(` ${title} `) }).sort((a, b) => normalized(b).length - normalized(a).length || Number(b.endsWith('.json')) - Number(a.endsWith('.json')))
  if (exact.length) return { file: exact[0], path: [], title: reportTitle(exact[0]) }
  const mk = summary?.marketing
  const sections = [
    [/\b(pricing|prices|pay|cost)\b/, 'pricing', 'Pricing'],
    [/\bfunnel\b/, 'funnel', 'Simulated buyer funnel'],
    [/\b(country|countries)\b/, 'by_country', 'Purchase intent by country'],
    [/\b(community|communities)\b/, 'by_community', 'Purchase intent by community'],
    [/\bage\b/, 'by_age', 'Purchase intent by age'],
    [/\bmessage(?:s)?\b/, 'messages_ranked', 'Message ranking'],
    [/\bplaybook\b/, 'playbook', 'Playbook']
  ]
  for (const [pattern, key, title] of sections) if (pattern.test(q) && mk?.[key] != null && available.includes('summary.json')) return { file: 'summary.json', path: ['marketing', key], title }
  const terms = q.split(' ').filter(term => term.length > 2 && !['show','visualize','display','chart','the','all','report','reports','saved','result','results','what','are','about','please','tell','give','and','with','this'].includes(term))
  if (!terms.length) return null
  const scored = available.map(file => { const name = normalized(file); return { file, score: terms.reduce((sum, term) => sum + (name.includes(term) ? 1 : 0), 0) } }).filter(x => x.score > 0).sort((a,b) => b.score-a.score || Number(b.file.endsWith('.json')) - Number(a.file.endsWith('.json')))
  if (scored.length && (scored[0].score === terms.length || /\b(show|visualize|display|report|chart|file)\b/.test(q))) return { file: scored[0].file, path: [], title: reportTitle(scored[0].file) }
  return null
}
