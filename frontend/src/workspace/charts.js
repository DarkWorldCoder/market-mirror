// Chart options (Apache ECharts) built from a saved run, and a small engine that answers common questions about a
// run with a chart key (rendered by the caller) from those files, without a model call. Every number here is simulated; captions say so.

const css = (name, fallback) => {
  const el = document.querySelector('.ws') || document.documentElement
  return getComputedStyle(el).getPropertyValue(name).trim() || fallback
}

export function palette() {
  return {
    text: css('--text', '#17181a'),
    muted: css('--muted', '#6c6f73'),
    line: css('--line', '#e6e6e1'),
    accent: css('--accent', '#1f6b4f'),
    // neutral single-series bars; --accent reads too close to --maybe, so a bar of counts would look like a verdict
    data: css('--data', '#4b5563'),
    warm: css('--warm', '#f26b2a'),
    yes: css('--yes', '#2f8f5b'),
    maybe: css('--maybe', '#d9a23b'),
    no: css('--no', '#c8584b'),
    series: ['#1f6b4f', '#f26b2a', '#4f7cd6', '#a259c4', '#d9a23b', '#2aa1a1', '#c8584b', '#7a8b2f', '#8c6d5a', '#5a6b8c']
  }
}

/** Small samples read better as counts: 1 of 28 rather than 3.6%. Returns null when n is 100 or more (or unknown),
 *  so the caller shows the percentage. The count is rounded from the saved percentage and clamped to 0..n. */
export function sampleCount(pct, n) {
  const p = Number(pct), size = Number(n)
  if (!Number.isFinite(p) || !Number.isInteger(size) || size <= 0 || size >= 100) return null
  const count = Math.min(size, Math.max(0, Math.round((p / 100) * size)))
  return { count, n: size, text: `${count} of ${size}`, pct: `${Math.round(p * 10) / 10}%` }
}

/** Saved decision -> the dw-decision tone class used across the workspace (go / iterate / stop). */
export function decisionTone(d) {
  const v = String(d || '')
  return /^(go|launch|proceed)$/i.test(v) ? 'go' : /no.?go|stop|reject/i.test(v) ? 'stop' : 'iterate'
}

/** "no_go" -> "No go"; empty stays empty. */
export const decisionText = (d) => String(d || '').replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase())

/** A survey verdict (yes / maybe / no) -> its palette colour; anything else gets the neutral data colour. */
export function verdictColor(verdict, p) {
  const v = String(verdict || '').toLowerCase()
  return v === 'yes' ? p.yes : v === 'maybe' ? p.maybe : v === 'no' ? p.no : p.data
}

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const short = (s, n = 26) => (String(s || '').length > n ? String(s).slice(0, n - 1) + '…' : String(s || ''))

function base(p) {
  return {
    animationDuration: 600,
    textStyle: { color: p.text, fontFamily: 'inherit' },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, confine: true },
    grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true }
  }
}

/** Would-convert split (yes / maybe / no) per segment, best first, with the shrunk "yes" when the run has it. */
export function segmentsOption(mk) {
  const rows = (mk?.by_segment || []).filter((r) => num(r.convert_yes) !== null).slice(0, 12)
  if (rows.length < 2) return null
  const p = palette()
  const cats = rows.map((r) => short(r.key)).reverse()
  const pick = (k) => rows.map((r) => num(r[k]) ?? 0).reverse()
  const series = [
    ['Would convert', 'convert_yes', p.yes],
    ['Maybe', 'convert_maybe', p.maybe],
    ['No', 'convert_no', p.no]
  ].map(([name, key, color]) => ({ name, type: 'bar', stack: 'v', data: pick(key), itemStyle: { color }, barMaxWidth: 18 }))
  const marker = rows.some((r) => num(r.convert_yes_shrunk) !== null) ? ['convert_yes_shrunk', 'Would convert, gap shrunk']
    : rows.some((r) => num(r.expected_convert_yes) !== null) ? ['expected_convert_yes', 'Expected, from stated chances'] : null
  if (marker) {
    series.push({
      name: marker[1],
      type: 'scatter',
      data: rows.map((r) => num(r[marker[0]])).reverse(),
      symbol: 'diamond',
      symbolSize: 11,
      itemStyle: { color: p.text }
    })
  }
  return {
    ...base(p),
    legend: { top: 0, textStyle: { color: p.muted, fontSize: 11 } },
    xAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%', color: p.muted, hideOverlap: true }, splitNumber: 4, splitLine: { lineStyle: { color: p.line } } },
    yAxis: { type: 'category', data: cats, axisLabel: { color: p.text, fontSize: 11 } },
    series,
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => `${v}%`, confine: true }
  }
}

/** Shares may overlap, so each objection gets its own bar rather than a part-to-whole slice. */
export function objectionsOption(mk) {
  const rows = (mk?.objections || []).filter(r => num(r.share) !== null)
  if (!rows.length) return null
  const p = palette()
  return {
    ...base(p),
    grid: { left: 8, right: 46, top: 12, bottom: 36, containLabel: true },
    xAxis: { type: 'value', name: 'People raising objection (%)', nameLocation: 'middle', nameGap: 25, axisLabel: { formatter: '{value}%', color: p.muted }, splitLine: { lineStyle: { color: p.line } } },
    yAxis: { type: 'category', data: rows.map(r => r.label).reverse(), axisLabel: { color: p.text, width: 145, overflow: 'truncate' } },
    tooltip: { trigger: 'axis', confine: true, valueFormatter: value => `${value}% of simulated people` },
    series: [{ type: 'bar', name: 'People raising objection', barMaxWidth: 18, data: rows.map(r => r.share).reverse(), itemStyle: { color: p.data, borderRadius: [0, 4, 4, 0] }, label: { show: true, position: 'right', formatter: '{c}%', color: p.muted } }]
  }
}

/** Expected click-through per ad in the feed test, best first. */
export function creativesOption(feed) {
  const per = feed?.summary?.per_creative || {}
  const names = Object.fromEntries((feed?.creatives || []).map((c) => [c.id, c.name || c.headline || c.id]))
  const ids = (feed?.summary?.ranked || Object.keys(per)).filter((id) => num(per[id]?.expected_ctr) !== null)
    .sort((a, b) => per[b].expected_ctr - per[a].expected_ctr)
  if (!ids.length) return null
  const p = palette()
  return {
    ...base(p),
    xAxis: { type: 'value', axisLabel: { formatter: '{value}%', color: p.muted, hideOverlap: true }, splitNumber: 4, splitLine: { lineStyle: { color: p.line } } },
    yAxis: { type: 'category', data: ids.map((id) => short(names[id] || id, 30)).reverse(), axisLabel: { color: p.text, fontSize: 11 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => `${v}% expected CTR (simulated)`, confine: true },
    series: [{
      type: 'bar',
      barMaxWidth: 16,
      data: ids.map((id, i) => ({ value: per[id].expected_ctr, itemStyle: { color: i === 0 ? p.warm : p.data, borderRadius: [0, 4, 4, 0] } })).reverse(),
      label: { show: true, position: 'right', formatter: '{c}%', color: p.muted, fontSize: 11 }
    }]
  }
}

/** Purchase intent on the 1-5 scale from free-text answers (SSR), as a distribution. */
export function intentOption(mk) {
  const pmf = mk?.overall?.ssr?.purchase?.pmf
  const p = palette()
  if (Array.isArray(pmf) && pmf.length === 5) {
    const labels = ['Definitely not', 'Probably not', 'Maybe', 'Probably', 'Definitely']
    return {
      ...base(p),
      xAxis: { type: 'category', data: labels, axisLabel: { color: p.muted, fontSize: 11 } },
      yAxis: { type: 'value', axisLabel: { formatter: '{value}%', color: p.muted, hideOverlap: true }, splitNumber: 4, splitLine: { lineStyle: { color: p.line } } },
      tooltip: { trigger: 'axis', valueFormatter: (v) => `${v}% of people (simulated)`, confine: true },
      series: [{
        type: 'bar',
        barMaxWidth: 42,
        data: pmf.map((v, i) => ({ value: Math.round(v * 1000) / 10, itemStyle: { color: [p.no, p.no, p.maybe, p.yes, p.yes][i], borderRadius: [5, 5, 0, 0] } }))
      }]
    }
  }
  const o = mk?.overall
  if (!o || num(o.convert_yes) === null) return null
  return {
    ...base(p),
    tooltip: { trigger: 'item', confine: true, formatter: (x) => `${x.name}: ${x.value}%` },
    series: [{
      type: 'pie',
      radius: ['50%', '75%'],
      label: { color: p.text, fontSize: 11 },
      data: [['Would convert', o.convert_yes, p.yes], ['Maybe', o.convert_maybe, p.maybe], ['No', o.convert_no, p.no]]
        .map(([name, value, color]) => ({ name, value: num(value) ?? 0, itemStyle: { color } }))
    }]
  }
}

/** People by country (or segment), for "who did we simulate". */
export function peopleOption(index, key = 'country') {
  const counts = {}
  for (const r of index || []) if (r[key] && (r.kind || 'persona') === 'persona') counts[r[key]] = (counts[r[key]] || 0) + 1
  const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10)
  if (!rows.length) return null
  const p = palette()
  return {
    ...base(p),
    xAxis: { type: 'value', axisLabel: { color: p.muted, hideOverlap: true }, splitNumber: 4, splitLine: { lineStyle: { color: p.line } }, minInterval: 1 },
    yAxis: { type: 'category', data: rows.map(([k]) => short(k)).reverse(), axisLabel: { color: p.text, fontSize: 11 } },
    series: [{ type: 'bar', barMaxWidth: 16, data: rows.map(([, v]) => v).reverse(), itemStyle: { color: p.data, borderRadius: [0, 4, 4, 0] } }]
  }
}

/** 3D market: every simulated person as a point, grouped by segment around the market map's entities. */
export function marketOption(index, graph) {
  const people = (index || []).filter((r) => (r.kind || 'persona') === 'persona')
  if (!people.length && !(graph?.nodes || []).length) return null
  const p = palette()
  const segments = [...new Set(people.map((r) => r.segment || 'No segment'))]
  const centre = (i, n, r = 60) => {
    const a = (2 * Math.PI * i) / Math.max(n, 1)
    return [r * Math.cos(a), r * Math.sin(a), 0]
  }
  let seed = 7
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647) * 2 - 1
  const series = segments.map((seg, i) => {
    const [cx, cy] = centre(i, segments.length)
    const pts = people.filter((r) => (r.segment || 'No segment') === seg).map((r) => ({
      name: r.name || `Person ${r.agent_id}`,
      value: [cx + rand() * 18, cy + rand() * 18, rand() * 22 + (r.age ? (r.age - 40) / 2 : 0)],
      country: r.country || '',
      age: r.age || ''
    }))
    return {
      type: 'scatter3D',
      name: short(seg, 30),
      data: pts,
      symbolSize: 6,
      itemStyle: { color: p.series[i % p.series.length], opacity: 0.85 },
      emphasis: { itemStyle: { color: p.warm } }
    }
  })
  const nodes = (graph?.nodes || []).slice(0, 40)
  if (nodes.length) {
    series.push({
      type: 'scatter3D',
      name: 'Market map',
      symbol: 'diamond',
      symbolSize: 12,
      label: { show: true, formatter: (x) => short(x.name, 18), textStyle: { color: p.text, fontSize: 10, backgroundColor: 'transparent' } },
      itemStyle: { color: p.text },
      data: nodes.map((n, i) => ({ name: n.name, value: [...centre(i, nodes.length, 22).slice(0, 2), 30], kind: (n.labels || []).filter((l) => l !== 'Entity').join(', ') }))
    })
  }
  return {
    tooltip: {
      confine: true,
      formatter: (x) => `<b>${x.name}</b><br>${x.seriesName}${x.data.country ? ' · ' + x.data.country : ''}${x.data.age ? ' · ' + x.data.age : ''}${x.data.kind ? '<br>' + x.data.kind : ''}`
    },
    legend: { type: 'scroll', bottom: 0, textStyle: { color: p.muted, fontSize: 11 } },
    grid3D: {
      show: false,
      viewControl: { autoRotate: true, autoRotateSpeed: 6, distance: 230, alpha: 24 },
      light: { main: { intensity: 1.1 }, ambient: { intensity: 0.5 } }
    },
    xAxis3D: { show: false, min: -100, max: 100 },
    yAxis3D: { show: false, min: -100, max: 100 },
    zAxis3D: { show: false, min: -60, max: 60 },
    series
  }
}

export function hasWebGL() {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    return false
  }
}

/** The same market as a 2D force layout, for browsers without WebGL: people around their segment hubs. */
export function market2dOption(index, graph) {
  const people = (index || []).filter((r) => (r.kind || 'persona') === 'persona').slice(0, 600)
  if (!people.length) return null
  const p = palette()
  const segments = [...new Set(people.map((r) => r.segment || 'No segment'))]
  const nodes = segments.map((seg, i) => ({ id: `seg:${seg}`, name: seg, category: i, symbolSize: 26, label: { show: true, color: p.text, fontSize: 11 } }))
  const links = []
  for (const r of people) {
    const seg = r.segment || 'No segment'
    nodes.push({ id: `p:${r.agent_id}`, name: r.name || `Person ${r.agent_id}`, category: segments.indexOf(seg), symbolSize: people.length < 80 ? 11 : 6, value: [r.country, r.age].filter(Boolean).join(' · ') })
    links.push({ source: `p:${r.agent_id}`, target: `seg:${seg}` })
  }
  const brand = (graph?.nodes || []).find((n) => (n.labels || []).includes('Brand'))
  if (brand) {
    nodes.push({ id: 'brand', name: brand.name, symbol: 'diamond', symbolSize: 30, itemStyle: { color: p.warm }, label: { show: true, color: p.text } })
    segments.forEach((seg) => links.push({ source: 'brand', target: `seg:${seg}`, lineStyle: { width: 2 } }))
  }
  return {
    tooltip: { confine: true, formatter: (x) => (x.dataType === 'node' ? `<b>${x.name}</b>${x.data.value ? '<br>' + x.data.value : ''}` : '') },
    legend: { type: 'scroll', bottom: 0, textStyle: { color: p.muted, fontSize: 11 } },
    color: p.series,
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      zoom: people.length < 80 ? 1 : 0.45,
      draggable: true,
      categories: segments.map((s) => ({ name: s })),
      data: nodes,
      links,
      force: people.length < 80 ? { repulsion: 260, edgeLength: [40, 110], gravity: 0.05 } : { repulsion: 45, edgeLength: [10, 50], gravity: 0.1 },
      labelLayout: { hideOverlap: true },
      lineStyle: { color: p.line, opacity: 0.7 },
      emphasis: { focus: 'adjacency' }
    }]
  }
}

// ---------------------------------------------------------------------------------------------------------------
// Chat engine: questions the saved run already answers. Returns {text, chart?} or null (then a model is asked).

const INTENTS = [
  { id: 'segments', words: /\b(segment|audience|target|who should|which group|best group)\b/i },
  { id: 'objections', words: /\b(objection|why not|why no|hesitat|worr|concern|stop|barrier|doubt)\b/i },
  { id: 'creatives', words: /\b(ad|ads|creative|headline|ctr|click|feed)\b/i },
  { id: 'intent', words: /\b(buy|convert|intent|purchase|how many|demand|sign ?up|would they)\b/i },
  { id: 'people', words: /\b(who|people|personas?|countr|where|demograph)\b/i },
  { id: 'decision', words: /\b(decision|verdict|go|launch|should i|summary|overall|result)\b/i }
]

export function localAnswer(question, run) {
  const mk = run?.summary?.marketing
  const intent = INTENTS.find((i) => i.words.test(question))?.id
  if (!intent) return null
  if (intent === 'segments' && mk) {
    const rate = (r) => num(r.expected_convert_yes) ?? num(r.convert_yes) ?? 0
    const rows = [...(mk.by_segment || [])].sort((a, b) => rate(b) - rate(a))
    const top = rows[0]
    const sh = mk.segment_shrink
    const thin = top && top.n < 10 ? ` Only ${top.n} people are in that segment, so treat it as an anecdote.` : ''
    const text = top
      ? `${top.key} leads, at ${rate(top)}% ${num(top.expected_convert_yes) !== null ? 'expected to convert (weighted by their stated chances)' : 'saying they would convert'}, simulated, n=${top.n}.` +
        thin + (sh?.note ? ` ${sh.note}` : ' Simulated gaps between segments run 2-4x larger than real ones, so read the order, not the size.')
      : 'This run has no segment breakdown.'
    return { text, chartKey: 'segments', caption: 'Would convert by segment, simulated' }
  }
  if (intent === 'objections' && mk?.objections?.length) {
    const o = mk.objections[0]
    const ex = o.examples?.[0]
    return {
      text: `The most common objection is "${o.label}" (${o.share}% of people).` + (ex ? ` One of them said: "${ex.text}"` : ''),
      chartKey: 'objections',
      caption: 'Objections raised, simulated'
    }
  }
  if (intent === 'creatives' && run.feed) {
    const per = run.feed.summary?.per_creative || {}
    const names = Object.fromEntries((run.feed.creatives || []).map((c) => [c.id, c.name || c.id]))
    const best = Object.keys(per).filter((id) => num(per[id]?.expected_ctr) !== null).sort((a, b) => per[b].expected_ctr - per[a].expected_ctr)[0]
    return {
      text: best ? `"${names[best] || best}" had the highest expected click-through in the simulated feed (${per[best].expected_ctr}%). Treat it as a direction and check it against your real ad results.` : 'The feed test has no click-through numbers.',
      chartKey: 'creatives',
      caption: 'Expected click-through per ad, simulated'
    }
  }
  if (intent === 'intent' && mk?.overall) {
    const o = mk.overall
    return {
      text: `${o.convert_yes}% said they would convert and ${o.convert_maybe}% maybe (n=${o.n}). Simulated people say yes more often than real ones, so treat this as an upper direction.`,
      chartKey: 'intent',
      caption: 'Purchase intent, simulated'
    }
  }
  if (intent === 'people' && run.index?.length) {
    const people = run.index.filter((r) => (r.kind || 'persona') === 'persona')
    return { text: `${people.length} invented people took part. They are fictional, built from your brief.`, chartKey: 'people', caption: 'Simulated people by country' }
  }
  if (intent === 'decision' && run.summary?.decision) {
    const d = run.summary.decision
    return { text: `${String(d.decision || '').toUpperCase()}: ${d.summary || ''}`.trim(), chartKey: 'decision', caption: 'Purchase intent, simulated' }
  }
  return null
}
