// Pure helpers for comparing two saved runs and for the chat home (run matching, evidence chats, Continue cards).
// No network and no model calls: everything here reads values that are already loaded.

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/** "FitLoop launch: does a free week convert? (v2)" -> "FitLoop launch" */
export function displayTitle(title) {
  const full = String(title || '').trim()
  return full.split(/[:(]/)[0].trim() || full
}

export function shortText(text, max) {
  const v = String(text || '')
  return v.length > max ? `${v.slice(0, max - 1).replace(/[\s,:;·-]+$/, '')}…` : v
}

/** "no_go" -> "No go", "ITERATE" -> "Iterate" (sentence case). */
export function decisionText(decision) {
  const v = String(decision || '').replaceAll('_', ' ').trim().toLowerCase()
  return v ? v.replace(/^./, (c) => c.toUpperCase()) : ''
}

export function decisionTone(decision) {
  const v = String(decision || '')
  return /^(go|launch|proceed)$/i.test(v) ? 'go' : /no.?go|stop|reject/i.test(v) ? 'stop' : 'iterate'
}

const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Runs named in the text (by folder name, full title or short title), in the order they appear. */
export function mentionedRuns(text, runs) {
  const hay = String(text || '').toLowerCase()
  const found = []
  for (const run of runs || []) {
    if (!run?.name) continue
    const candidates = [[run.name, 2], [run.title, 1], [displayTitle(run.title), 1]]
    for (const [label, priority] of candidates) {
      const needle = String(label || '').trim().toLowerCase()
      if (needle.length < 3) continue
      const re = new RegExp(`(^|[^a-z0-9_-])${escape(needle)}(?![a-z0-9_-])`, 'g')
      let m
      while ((m = re.exec(hay))) {
        const start = m.index + m[1].length
        found.push({ name: run.name, start, end: start + needle.length, priority })
        if (re.lastIndex === m.index) re.lastIndex++
      }
    }
  }
  // longest, most specific match wins where matches overlap (so "fitloop_launch" is not also read as "fitloop")
  found.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start) || b.priority - a.priority)
  const taken = [], names = []
  for (const f of found) {
    if (taken.some((t) => f.start < t.end && t.start < f.end)) continue
    taken.push(f)
    if (!names.includes(f.name)) names.push(f.name)
  }
  return names
}

/** True when the message asks to compare saved experiments (answered locally, no model call). */
export function isCompareRequest(text, runs) {
  const t = String(text || '')
  const mentioned = mentionedRuns(t, runs)
  if (/\b(compare|comparing|comparison|side[- ]by[- ]side)\b/i.test(t)) {
    return mentioned.length > 0 || /\b(experiments?|runs?|tests?|results?|reports?)\b/i.test(t)
  }
  return /\b(vs\.?|versus)\b/i.test(t) && mentioned.length >= 2
}

/** Pick A and B: runs named in the text first, then the selected run, then the newest runs. */
export function pickCompareRuns(text, runs, selected = '') {
  const list = (runs || []).filter((r) => r?.name)
  const known = new Set(list.map((r) => r.name))
  const order = [...mentionedRuns(text, list)]
  if (selected && known.has(selected) && !order.includes(selected)) order.push(selected)
  for (const r of list) if (!order.includes(r.name)) order.push(r.name)
  return { a: order[0] || '', b: order[1] || '' }
}

/** An earlier chat that opened the same saved evidence (same run, same opening request), newest first. */
export function findEvidenceChat(chats, run, prompt) {
  if (!run || !prompt) return null
  return (chats || []).find((c) => {
    const first = Array.isArray(c?.messages) ? c.messages[0] : null
    return c.run === run && first?.role === 'user' && first.evidenceRun === run && first.content === prompt
  }) || null
}

export function evidenceTitle(view, runTitle) {
  return `${view} · ${shortText(displayTitle(runTitle), 40)}`
}

const chatKey = (c) => `${String(c.title || '').trim().toLowerCase()}|${c.run || ''}`

/**
 * Continue cards: recent chats (one per title + run), with the last slot kept for the newest experiment
 * that has no chat yet. `chats` and `runs` are newest first.
 */
export function continueEntries(chats, runs, limit = 3) {
  const real = (chats || []).filter((c) => Array.isArray(c?.messages) && c.messages.length)
  const seen = new Set(), picked = []
  for (const c of real) {
    const key = chatKey(c)
    if (seen.has(key)) continue
    seen.add(key)
    picked.push(c)
  }
  const chatRuns = new Set(real.map((c) => c.run).filter(Boolean))
  const freeRuns = (runs || []).filter((r) => r?.name && !chatRuns.has(r.name))
  const items = picked.slice(0, freeRuns.length ? limit - 1 : limit).map((chat) => ({ kind: 'chat', chat }))
  for (const run of freeRuns) {
    if (items.length >= limit) break
    items.push({ kind: 'run', run })
  }
  return items
}

const round1 = (v) => Math.round(v * 10) / 10

/** A share of people: "x of n (y%)" when n < 100, else "y%". */
export function shareText(pct, n, count = null) {
  if (num(pct) === null) return null
  const base = num(n)
  if (base !== null && base > 0 && base < 100) {
    const x = num(count) ?? Math.round((pct / 100) * base)
    return `${x} of ${base} (${Math.round(pct)}%)`
  }
  return `${round1(pct)}%`
}

const segRate = (s) => num(s?.expected_convert_yes) ?? num(s?.convert_yes)

function segments(mk) {
  return (mk?.by_segment || []).filter((s) => s && segRate(s) !== null)
}

function segmentText(s) {
  return s ? `${s.key}: ${shareText(segRate(s), s.n)} would buy` : null
}

export function rankedAds(feed) {
  const per = feed?.summary?.per_creative || {}
  const names = Object.fromEntries((feed?.creatives || []).map((c) => [c.id, c.name || c.id]))
  return Object.keys(per)
    .map((id) => ({ id, name: names[id] || id, ctr: num(per[id]?.expected_ctr) ?? num(per[id]?.ctr) }))
    .filter((ad) => ad.ctr !== null)
    .sort((a, b) => b.ctr - a.ctr)
}

function social(story) {
  const platforms = story?.platforms && typeof story.platforms === 'object' ? story.platforms : null
  if (!platforms) return null
  const entries = Array.isArray(platforms) ? platforms.map((p) => [p.platform || p.name || '', p]) : Object.entries(platforms)
  const out = {}
  for (const key of ['total_posts', 'comments', 'likes']) {
    const parts = entries.filter(([, p]) => num(p?.[key]) !== null).map(([name, p]) => [name, p[key]])
    if (!parts.length) { out[key] = null; continue }
    const total = parts.reduce((s, [, v]) => s + v, 0)
    const label = (name) => (name ? name.charAt(0).toUpperCase() + name.slice(1) : 'Other')
    out[key] = parts.length > 1 ? `${total.toLocaleString()} (${parts.map(([name, v]) => `${label(name)} ${v.toLocaleString()}`).join(' · ')})` : total.toLocaleString()
  }
  return out
}

function hotLeads(pitch) {
  const h = pitch?.hot_leads
  return Array.isArray(h) ? h.length : num(h)
}

const lead = (a, b) => (num(a) === null || num(b) === null || a === b ? null : a > b ? 0 : 1)
const ordinal = ['Main reason', 'Second reason', 'Third reason']

/** Too close to call on would buy: under 5 points apart, or fewer than 30 answers in the smaller run. */
export function wouldBuyGap(A, B) {
  const a = A?.mk?.overall, b = B?.mk?.overall
  if (!a || !b || num(a.convert_yes) === null || num(b.convert_yes) === null) return null
  const gap = Math.abs(a.convert_yes - b.convert_yes)
  const small = Math.min(num(a.n) ?? 0, num(b.n) ?? 0)
  return { gap, small, tooClose: gap < 5 || small < 30, lead: gap < 5 || small < 30 ? null : lead(a.convert_yes, b.convert_yes) }
}

/**
 * Everything Compare shows, grouped in sections. Each run is
 * { name, title, decision, decisionSummary, count, mk, feed, pitch, story }.
 * Values are strings, { pill, tone } or { list: [...] }; every value is simulated.
 */
export function compareSections(A, B) {
  if (!A || !B) return []
  const runs = [A, B]
  const each = (fn) => runs.map((r) => fn(r))
  const o = (r) => r.mk?.overall || {}
  const n = (r) => num(o(r).n)
  const gap = wouldBuyGap(A, B)
  const sections = []

  sections.push({ title: 'At a glance', rows: [
    { label: 'Decision', values: each((r) => (r.decision ? { pill: decisionText(r.decision), tone: decisionTone(r.decision) } : null)) },
    { label: 'In one line', values: each((r) => r.decisionSummary || null) },
    { label: 'Simulated people', values: each((r) => (num(r.count) !== null ? r.count.toLocaleString() : null)) },
    { label: 'Answered the survey', values: each((r) => {
      const answered = num(r.mk?.answered) ?? n(r)
      const people = num(r.count) ?? num(r.mk?.people)
      if (answered === null) return null
      if (people === null || people <= 0 || answered > people) return answered.toLocaleString()
      const pct = (answered / people) * 100
      return people < 100 ? `${answered} of ${people} (${Math.round(pct)}%)` : `${answered.toLocaleString()} (${Math.round(pct)}%)`
    }) }
  ] })

  sections.push({ title: 'Buying intent', rows: [
    { label: 'Would buy', values: each((r) => shareText(o(r).convert_yes, n(r))), lead: gap?.lead ?? null },
    { label: 'Maybe', values: each((r) => shareText(o(r).convert_maybe, n(r))) },
    { label: 'Would not buy', values: each((r) => shareText(o(r).convert_no, n(r))) },
    { label: 'Would click', values: each((r) => shareText(o(r).click_yes, n(r))) },
    { label: 'Interest', values: each((r) => (num(o(r).interest) !== null ? `${o(r).interest} / 10` : null)) },
    { label: 'Trust', values: each((r) => (num(o(r).trust) !== null ? `${o(r).trust} / 10` : null)) }
  ] })

  sections.push({ title: 'Audiences', rows: [
    { label: 'Strongest', values: each((r) => segmentText([...segments(r.mk)].sort((x, y) => segRate(y) - segRate(x))[0])) },
    { label: 'Weakest', values: each((r) => { const s = segments(r.mk); return s.length > 1 ? segmentText([...s].sort((x, y) => segRate(x) - segRate(y))[0]) : null }) },
    { label: 'Audiences tested', values: each((r) => (r.mk?.by_segment?.length ? String(r.mk.by_segment.length) : null)) }
  ] })

  if (runs.some((r) => r.mk?.objections?.length)) {
    sections.push({ title: 'Why people said no', rows: ordinal.map((label, i) => ({
      label,
      values: each((r) => {
        const ob = r.mk?.objections?.[i]
        return ob ? `${ob.label}: ${shareText(ob.share, n(r), num(ob.count))}` : null
      })
    })) })
  }

  if (runs.some((r) => rankedAds(r.feed).length)) {
    const best = each((r) => rankedAds(r.feed)[0] || null)
    sections.push({ title: 'Ads in the feed', rows: [
      { label: 'Best ad (expected click-through)', values: best.map((ad) => (ad ? `${ad.name}: ${ad.ctr}%` : null)), lead: lead(best[0]?.ctr, best[1]?.ctr) },
      { label: 'Every ad, ranked', values: each((r) => { const ads = rankedAds(r.feed); return ads.length ? { list: ads.map((ad) => `${ad.name}: ${ad.ctr}%`) } : null }) }
    ] })
  }

  if (runs.some((r) => r.pitch)) {
    sections.push({ title: 'Sales pitch', rows: [
      { label: 'Pitch score', values: each((r) => (num(r.pitch?.pitch_score) !== null ? `${r.pitch.pitch_score} / 100` : null)) },
      { label: 'Said yes after the pitch', values: each((r) => shareText(r.pitch?.verdict_after?.yes, num(r.pitch?.people_pitched) ?? num(r.pitch?.answered))) },
      { label: 'Hot leads', values: each((r) => (hotLeads(r.pitch) !== null ? String(hotLeads(r.pitch)) : null)) }
    ] })
  }

  if (runs.some((r) => social(r.story))) {
    const s = each((r) => social(r.story) || {})
    sections.push({ title: 'Social activity', rows: [
      { label: 'Posts', values: s.map((x) => x.total_posts ?? null) },
      { label: 'Comments', values: s.map((x) => x.comments ?? null) },
      { label: 'Likes', values: s.map((x) => x.likes ?? null) }
    ] })
  }
  return sections
}

/** One plain sentence on which way the two runs point. */
export function compareVerdict(A, B) {
  if (!A || !B) return ''
  const ta = displayTitle(A.title || A.name), tb = displayTitle(B.title || B.name)
  const gap = wouldBuyGap(A, B)
  const da = decisionText(A.decision), db = decisionText(B.decision)
  const decisions = da && db ? (da === db ? `both say ${da}` : `${ta} says ${da} and ${tb} says ${db}`) : ''
  if (gap && gap.lead !== null) {
    const [w, l] = gap.lead === 0 ? [A, B] : [B, A]
    return `${displayTitle(w.title || w.name)} leans ahead: ${round1(w.mk.overall.convert_yes)}% would buy against ${round1(l.mk.overall.convert_yes)}%${decisions ? `, and ${decisions}` : ''}.`
  }
  if (gap) return `Neither run is clearly ahead on would buy${decisions ? `; ${decisions}` : ''}.`
  const surveyed = [A, B].filter((r) => num(r.mk?.overall?.convert_yes) !== null)
  const lead = surveyed.length === 1
    ? `Only ${displayTitle(surveyed[0].title || surveyed[0].name)} has a buyer survey, so would buy cannot be compared`
    : 'Neither run has a buyer survey to compare'
  return `${lead}${decisions ? `; ${decisions}` : ''}.`
}

export function compareGapNote(A, B) {
  const gap = wouldBuyGap(A, B)
  if (!gap) return ''
  if (gap.tooClose) return `The would-buy gap is ${gap.gap.toFixed(1)} points with ${gap.small || 'few'} answers in the smaller run: too close to call. Check with real people before choosing.`
  return `The would-buy gap is ${gap.gap.toFixed(1)} points. Simulated gaps tend to be larger than real ones, so treat it as which way to lean, not by how much.`
}
