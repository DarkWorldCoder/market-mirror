// Predicted brain response per ad (Meta TRIBE v2 via the owner's sidecar), from a run's brain_response.json or the
// feed-test rows that carry it. A research view shown beside the simulated buyers; never a score.
import { palette } from './charts.js'

export const BRAIN_LABEL = "Predicted for an average viewer by Meta's TRIBE v2 research model (noncommercial license). It predicts brain activity, not attention, feelings, memory or buying. Not validated for ads."

const GROUPS = [['visual', 0], ['hearing', 1], ['language', 2], ['cortex', null]]

export function clock(s) {
  const v = Math.max(0, Math.round(Number(s) || 0))
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, '0')}`
}

/** Rows {id, name, status, kind, summary?, line?, reason?} from brain_response.json, else from feed_test.json. */
export function brainRows(brain, feed) {
  const rows = Array.isArray(brain?.creatives) ? brain.creatives.filter((r) => r && typeof r === 'object') : []
  if (rows.length) return rows
  return (feed?.creatives || [])
    .filter((c) => c?.brain_response?.summary && typeof c.brain_response.summary === 'object')
    .map((c) => ({ id: c.id, name: c.name, status: 'ok', kind: c.brain_response.summary.kind, summary: c.brain_response.summary, line: c.brain_response.line || '' }))
}

/** The top peaks of each group as "label: 0:04-0:06" strings. */
export function peakText(summary) {
  const groups = summary?.groups || {}
  return GROUPS.map(([key]) => groups[key]).filter((g) => g?.peaks?.length).map((g) => {
    const spans = g.peaks.slice(0, 2).map((p) => clock(p.start) === clock(p.end) ? clock(p.start) : `${clock(p.start)}-${clock(p.end)}`)
    return `${g.label}: ${spans.join(', ')}`
  })
}

/** ECharts line option: one line per group, z within the clip, seconds on x. Null when there is nothing to draw. */
export function brainOption(summary) {
  const seconds = Array.isArray(summary?.seconds) ? summary.seconds : []
  const groups = summary?.groups || {}
  const p = palette()
  const series = GROUPS.filter(([key]) => Array.isArray(groups[key]?.z) && groups[key].z.length === seconds.length).map(([key, slot]) => ({
    name: groups[key].label || key,
    type: 'line',
    showSymbol: false,
    smooth: false,
    data: seconds.map((t, i) => [t, groups[key].z[i]]),
    lineStyle: { width: slot === null ? 1.2 : 2, type: slot === null ? 'dashed' : 'solid', color: slot === null ? p.muted : p.series[slot] },
    itemStyle: { color: slot === null ? p.muted : p.series[slot] }
  }))
  if (seconds.length < 2 || !series.length) return null
  return {
    animation: false,
    grid: { left: 34, right: 10, top: 30, bottom: 26 },
    legend: { top: 0, textStyle: { color: p.muted, fontSize: 11 }, itemWidth: 14, itemHeight: 6 },
    tooltip: { trigger: 'axis', confine: true, valueFormatter: (v) => `${Number(v).toFixed(2)} z (within this ad, predicted)` },
    xAxis: { type: 'value', min: seconds[0], max: seconds[seconds.length - 1], axisLabel: { color: p.muted, formatter: (v) => clock(v), hideOverlap: true }, splitLine: { show: false } },
    yAxis: { type: 'value', name: 'z', nameTextStyle: { color: p.muted }, axisLabel: { color: p.muted }, splitLine: { lineStyle: { color: p.line } } },
    series
  }
}
