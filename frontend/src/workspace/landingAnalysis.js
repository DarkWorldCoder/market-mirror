// Landing page analysis for a saved run: how the simulated people moved from the ad to the page and the signup,
// where and why they left, which ad sent the people who went furthest, how far they got down the page and what the
// conversion lab suggests fixing first. Pure functions over saved files; nothing here calls a model.
//
// Sources, all optional:
//   feed_test.json      sessions[].ad / sessions[].landing (per person), summary.per_creative[id].landing,
//                       landing (what the page shows), drop_causes (reasons grouped by Jev, when a key was set)
//   cro_lab.json        older lab file: landing_teardown {scroll_zones, sentiment_pins, top_cro_actions},
//                       causal_whatif {attributes}; or the newer envelopes below nested under the same keys
//   landing_teardown.json  five-second and scroll test: summary {page, read_until, would_continue, confusing, ...}
//   causal_whatif.json     choice experiment: summary {effects: [{attribute, level, versus, effect_pts, lo, hi}]}
//   website_test.json      browser journeys: sessions[].status / steps / checks, summary, milestones

export const LANDING_FILES = ['feed_test.json', 'cro_lab.json', 'landing_teardown.json', 'causal_whatif.json', 'website_test.json']

const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v)
const arr = (v) => (Array.isArray(v) ? v : [])
const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v) => (typeof v === 'string' ? v.trim() : '')
const pct = (k, n) => (n ? Math.round((1000 * k) / n) / 10 : null)
const clean = (s) => str(s).replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, '').replace(/\s+/g, ' ').trim()

/** Which of the landing files a run has saved. */
export function landingFilesIn(files) {
  const have = new Set(arr(files))
  return LANDING_FILES.filter((f) => have.has(f))
}

// --------------------------------------------------------------------------
// 1. Funnel
// --------------------------------------------------------------------------

function withDrops(steps, ordered = true) {
  return steps.map((s, i) => {
    const prev = i ? steps[i - 1].n : null
    const kept = ordered && prev ? pct(s.n, prev) : null
    return { ...s, keptPct: kept, dropPct: kept == null ? null : Math.round((100 - kept) * 10) / 10, lost: ordered && prev != null ? Math.max(0, prev - s.n) : null }
  })
}

const sessionsOf = (feed) => arr(feed?.sessions).filter((s) => isObj(s) && isObj(s.ad))

/** Ad to signup funnel from the feed test, counted per simulated session. */
export function feedFunnel(feed) {
  const ss = sessionsOf(feed)
  const landed = ss.filter((s) => isObj(s.landing))
  if (ss.length && landed.length) {
    const has = (k) => landed.some((s) => k in s.landing)
    const steps = [
      { key: 'shown', label: 'Ad shown in a feed', n: ss.length },
      ...(ss.some((s) => 'noticed' in s.ad) ? [{ key: 'noticed', label: 'Noticed the ad', n: ss.filter((s) => s.ad.noticed === true).length }] : []),
      { key: 'clicked', label: 'Clicked', n: ss.filter((s) => s.ad.click === true).length },
      { key: 'loaded', label: 'Page loaded', n: landed.filter((s) => s.landing.loaded === true).length },
      ...(has('read') ? [{ key: 'read', label: 'Read the page', n: landed.filter((s) => s.landing.read === true).length }] : []),
      { key: 'started', label: 'Started signup', n: landed.filter((s) => s.landing.started_form === true).length },
      { key: 'converted', label: 'Converted', n: landed.filter((s) => s.landing.completed === true).length }
    ]
    return { steps: withDrops(steps), ordered: true, basis: 'Counted from every simulated feed session in feed_test.json.' }
  }
  // older runs: only the per-ad totals were saved
  const per = Object.values(isObj(feed?.summary?.per_creative) ? feed.summary.per_creative : {}).filter(isObj)
  const lfs = per.map((m) => m.landing).filter(isObj)
  if (!lfs.length) return null
  const sum = (rows, k) => rows.reduce((t, r) => t + (num(r[k]) || 0), 0)
  const steps = [
    { key: 'shown', label: 'Ad shown in a feed', n: sum(per, 'impressions') },
    { key: 'clicked', label: 'Clicked', n: sum(lfs, 'clicks') },
    { key: 'loaded', label: 'Page loaded', n: sum(lfs, 'page_loaded') },
    { key: 'started', label: 'Started signup', n: sum(lfs, 'form_started') },
    { key: 'converted', label: 'Converted', n: sum(lfs, 'converted') }
  ].filter((s, i) => i || s.n)
  return { steps: withDrops(steps), ordered: true, basis: 'Added up from the per-ad totals in feed_test.json.' }
}

/** Browser journey counts from a website test. Milestones are counts, not a guaranteed order. */
export function websiteFunnel(web) {
  if (!isObj(web) || !isObj(web.summary)) return null
  const s = web.summary
  // with session records, count them (zero when none started, e.g. all stopped by the budget); the summary is a fallback
  const sessions = arr(web.sessions).filter(isObj)
  const started = sessions.length ? sessions.filter((x) => x.started !== false).length : num(s.visitors) || 0
  const milestones = isObj(web.milestones) ? web.milestones : {}
  const order = arr(web.checks).map((c) => c?.name).filter((n) => n in milestones)
  for (const k of Object.keys(milestones)) if (!order.includes(k)) order.push(k)
  const steps = [{ key: 'visitors', label: 'Visitors started', n: started }]
  for (const k of order) steps.push({ key: `check:${k}`, label: `Check passed: ${k.replace(/_/g, ' ')}`, n: num(milestones[k]) || 0 })
  if (!order.includes(web.goal_check)) {
    const goal = (num(s.goal_observed) || 0) + (num(s.already_satisfied) || 0)
    steps.push({ key: 'goal', label: web.goal_check ? 'Goal confirmed' : 'Said they finished (unverified)', n: web.goal_check ? goal : num(s.completed_unverified) || 0 })
  }
  return { steps: withDrops(steps, false), ordered: false, basis: 'Counts of synthetic visitors in website_test.json. Each check counts on its own, so the steps are not a strict order.' }
}

// --------------------------------------------------------------------------
// 2. Where and why people left
// --------------------------------------------------------------------------

// reasons the simulator writes itself, not the person's own words
const SYSTEM_REASON = /^(left before the page loaded|gave up when the form showed an error|price \(.*\) exceeds comfortable|triggered dealbreaker:|polite interest, but backed out)/i
export const isSystemReason = (text) => SYSTEM_REASON.test(str(text))

const GATE_CAUSES = {
  network_timeout: { key: 'slow', label: 'Page took too long to load' },
  wallet_limit: { key: 'budget', label: 'Price above what they would spend' },
  dealbreaker: { key: 'dealbreaker', label: 'Hit one of their dealbreakers' },
  say_vs_do_gap: { key: 'backed_out', label: 'Backed out at the commitment step' }
}
// free-text reasons: the first group whose words appear in the reason (simple rules, not a model)
export const REASON_GROUPS = [
  { key: 'slow', label: 'Page took too long to load', re: /left before the page loaded|too slow|slow to load|took too long|loading/i },
  { key: 'form_error', label: 'Form error or a code they could not get', re: /form showed an error|asked for a code|\botp\b|verification code/i },
  { key: 'card', label: 'Asked for card details up front', re: /\bcard\b|credit|debit|\bcvv\b|payment details|billing details/i },
  { key: 'budget', label: 'Price above what they would spend', re: /exceeds comfortable/i },
  { key: 'price', label: 'Price or currency', re: /price|pricing|expensive|afford|\busd\b|dollars?|\$|₹|€|£|per month|subscription|cost/i },
  { key: 'dealbreaker', label: 'Hit one of their dealbreakers', re: /dealbreaker/i },
  { key: 'backed_out', label: 'Backed out at the commitment step', re: /backed out at commitment/i },
  { key: 'trust', label: 'Wanted more proof or trust', re: /proof|reviews?|trust|scam|privacy|tracking|permission|not sure|unsure|doubt/i },
  { key: 'language', label: 'Language', re: /english|language|tagalog|hindi|swahili|translat/i },
  { key: 'device', label: 'Phone, data or offline needs', re: /phone|device|android|iphone|offline|storage|\bdata\b/i },
  { key: 'alternative', label: 'Preferred another option', re: /app store|play store|youtube|instead|rather|already (use|have)|free (videos|alternative)/i },
  { key: 'form', label: 'Too much to fill in', re: /\bform\b|fields?|sign ?up|account|password|email/i }
]
const OTHER = { key: 'other', label: 'Other reasons' }

export function reasonGroup(text, gate = '') {
  if (GATE_CAUSES[gate]) return GATE_CAUSES[gate]
  const t = str(text)
  return REASON_GROUPS.find((g) => g.re.test(t)) || OTHER
}

function who(s) {
  return [str(s.name), str(s.segment), str(s.country)].filter(Boolean).join(' · ')
}

/** Every text a quote may come from: what the people wrote in the saved files. */
export function savedTexts(feed, web, teardown) {
  const out = new Set()
  const add = (t) => { const v = str(t); if (v) out.add(v) }
  for (const s of sessionsOf(feed)) { add(s.landing?.drop_reason); add(s.landing?.thought); add(s.ad?.thought) }
  for (const m of Object.values(isObj(feed?.summary?.per_creative) ? feed.summary.per_creative : {})) {
    for (const r of arr(m?.landing?.drop_reasons)) add(r?.reason)
  }
  for (const v of arr(web?.sessions)) for (const st of arr(v?.steps)) add(st?.action?.reason)
  const sum = teardown?.summary
  for (const c of arr(sum?.confusing)) for (const q of arr(c?.quotes)) add(q)
  for (const c of arr(sum?.missing_to_decide)) for (const q of arr(c?.quotes)) add(q)
  return out
}

/** A quote is shown only when it is word for word in the saved data. */
export function quoteExists(text, saved) {
  const t = str(text)
  return Boolean(t) && saved instanceof Set && saved.has(t)
}

function stage(s) {
  const l = s.landing
  if (l.completed) return null
  if (!l.loaded) return 'before_load'
  if (l.started_form) return 'form'
  return 'page'
}
export const STAGE_LABELS = { before_load: 'Left before the page loaded', page: 'Left while on the page', form: 'Left at the signup form' }

/** Ranked reasons the clickers did not convert, with up to two of their own words per reason. */
export function feedDropCauses(feed) {
  const ss = sessionsOf(feed)
  const left = ss.filter((s) => isObj(s.landing) && s.ad.click === true && !s.landing.completed)
  const saved = savedTexts(feed)
  const stages = {}
  for (const s of left) { const k = stage(s); if (k) stages[k] = (stages[k] || 0) + 1 }
  const stageRows = ['before_load', 'page', 'form'].filter((k) => stages[k]).map((k) => ({ key: k, label: STAGE_LABELS[k], n: stages[k] }))

  const jev = arr(feed?.drop_causes?.overall).filter((c) => isObj(c) && str(c.cause))
  if (jev.length) {
    const byReason = new Map(left.map((s) => [str(s.landing.drop_reason), s]))
    const total = jev.reduce((t, c) => t + (num(c.count) || 0), 0)
    return {
      left: left.length, stages: stageRows, method: 'jev', total,
      note: `Reasons grouped by the Jev decision model (${feed.drop_causes.labelled ?? total} of ${feed.drop_causes.reasons ?? total} reasons). Simulated.`,
      causes: jev.map((c) => ({
        key: str(c.cause), label: str(c.cause).replace(/_/g, ' ').replace(/^\w/, (m) => m.toUpperCase()), count: num(c.count) || 0,
        sharePct: num(c.share_pct) ?? pct(num(c.count) || 0, total),
        quotes: arr(c.examples).filter((q) => quoteExists(q, saved) && !isSystemReason(q)).slice(0, 2).map((q) => ({ text: str(q), who: byReason.has(str(q)) ? who(byReason.get(str(q))) : '', kind: 'reason' })),
        events: arr(c.examples).filter((q) => isSystemReason(q)).slice(0, 1).map(str)
      }))
    }
  }

  const withReason = left.filter((s) => str(s.landing.drop_reason) || GATE_CAUSES[s.landing.friction_gate])
  if (!withReason.length) return left.length ? { left: left.length, stages: stageRows, method: 'none', total: 0, causes: [], note: 'No reasons were saved for the people who left.' } : null
  const groups = new Map()
  for (const s of withReason) {
    const reason = str(s.landing.drop_reason)
    const g = reasonGroup(reason, s.landing.friction_gate)
    if (!groups.has(g.key)) groups.set(g.key, { key: g.key, label: g.label, count: 0, quotes: [], events: [] })
    const row = groups.get(g.key)
    row.count++
    const kind = reason && !isSystemReason(reason) ? 'reason' : 'thought'
    const own = kind === 'reason' ? reason : str(s.landing.thought)
    if (own && row.quotes.length < 2 && quoteExists(own, saved) && !row.quotes.some((q) => q.text === own)) row.quotes.push({ text: own, who: who(s), kind })
    if (reason && isSystemReason(reason) && !row.events.includes(reason) && row.events.length < 1) row.events.push(reason)
  }
  const total = withReason.length
  const causes = [...groups.values()].map((c) => ({ ...c, sharePct: pct(c.count, total) }))
    .sort((a, b) => b.count - a.count || (a.key === 'other') - (b.key === 'other'))
  return { left: left.length, stages: stageRows, method: 'rules', total, causes,
    note: 'Each reason is put in the first group whose words it uses. Simple rules, not a model. Simulated.' }
}

const WEB_STATUS = {
  left: 'Chose to leave', step_limit: 'Ran out of steps', completed_unverified: 'Said they finished, not confirmed',
  blocked: 'Blocked by the site or a safety rule', execution_failed: 'Test failure', loop_detected: 'Repeated the same action',
  budget_exhausted: 'Test limit reached'
}

/** Why website-test visitors did not reach the goal: their status, with the last reason they gave. */
export function websiteDropCauses(web) {
  const rows = arr(web?.sessions).filter((v) => isObj(v) && WEB_STATUS[v.status])
  if (!rows.length) return null
  const saved = savedTexts(null, web)
  const groups = new Map()
  for (const v of rows) {
    if (!groups.has(v.status)) groups.set(v.status, { key: v.status, label: WEB_STATUS[v.status], count: 0, quotes: [], events: [] })
    const g = groups.get(v.status)
    g.count++
    const steps = arr(v.steps)
    const last = steps.length ? steps[steps.length - 1] : null
    const reason = str(last?.action?.reason)
    if (v.status === 'left' && reason && g.quotes.length < 2 && quoteExists(reason, saved)) g.quotes.push({ text: reason, who: [str(v.name), str(v.segment), str(last?.title)].filter(Boolean).join(' · '), kind: 'reason' })
    if (v.stop_reason && !g.events.includes(v.stop_reason) && g.events.length < 1) g.events.push(str(v.stop_reason))
  }
  const total = rows.length
  return {
    left: total, stages: [], method: 'status', total,
    note: 'Grouped by how each visitor\'s journey ended. Errors and blocked actions are not lack of interest.',
    causes: [...groups.values()].map((c) => ({ ...c, sharePct: pct(c.count, total) })).sort((a, b) => b.count - a.count)
  }
}

// --------------------------------------------------------------------------
// 3. Per-ad comparison
// --------------------------------------------------------------------------

/** Each ad's clickers on the page. A leader is named only when one ad is ahead on its own. */
export function adLandingRows(feed) {
  const creatives = new Map(arr(feed?.creatives).filter(isObj).map((c) => [String(c.id), c]))
  const per = isObj(feed?.summary?.per_creative) ? feed.summary.per_creative : {}
  const ss = sessionsOf(feed)
  const ids = [...new Set([...Object.keys(per), ...ss.map((s) => String(s.creative_id))])].filter((id) => id && id !== 'undefined')
  const rows = []
  for (const id of ids) {
    const mine = ss.filter((s) => String(s.creative_id) === id && s.ad.click === true && isObj(s.landing))
    const lf = isObj(per[id]?.landing) ? per[id].landing : null
    const read = mine.some((s) => 'read' in s.landing) ? mine.filter((s) => s.landing.read === true).length : null
    const row = mine.length
      ? { clicks: mine.length, loaded: mine.filter((s) => s.landing.loaded).length, read, started: mine.filter((s) => s.landing.started_form).length, converted: mine.filter((s) => s.landing.completed).length }
      : lf ? { clicks: num(lf.clicks) || 0, loaded: num(lf.page_loaded) || 0, read: null, started: num(lf.form_started) || 0, converted: num(lf.converted) || 0 } : null
    if (!row || !row.clicks) continue
    const c = creatives.get(id) || {}
    rows.push({ id, name: str(c.name) || str(c.headline) || id, platform: str(c.platform), shown: num(per[id]?.impressions), ...row, convertedPct: pct(row.converted, row.clicks) })
  }
  if (rows.length < 2) return null
  const score = (r) => [r.converted, r.started, r.read ?? 0, r.loaded]
  const cmp = (a, b) => { const x = score(a), y = score(b); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return y[i] - x[i]; return b.clicks - a.clicks }
  rows.sort(cmp)
  const top = rows[0], second = rows[1]
  // the first score that differs decides the lead, and the sentence says which one it was
  const by = score(top).findIndex((v, i) => v !== score(second)[i])
  const lead = by >= 0 && (top.converted || top.started)
  const tiedSignups = top.converted ? `Signups are tied at ${top.converted}; ` : ''
  const because = [
    () => `${top.name} sent the most people who signed up (${top.converted} of ${top.clicks} who clicked).`,
    () => `${tiedSignups}${top.name} had the most people start signup (${top.started} of ${top.clicks} who clicked).`,
    () => `${tiedSignups || 'Signup starts are tied; '}${top.name} had the most people read the page (${top.read} of ${top.clicks} who clicked).`,
    () => `${tiedSignups || 'Signup starts are tied; '}${top.name} had the most pages load (${top.loaded} of ${top.clicks} who clicked).`
  ]
  const fewClicks = rows.every((r) => r.clicks < 10)
  return {
    rows, leader: lead ? top.id : null,
    leaderText: lead ? because[by]() : 'No ad is clearly ahead on the page.',
    note: fewClicks ? 'Every ad had fewer than 10 clicks, so one or two people can change this order. Simulated.' : 'Simulated people, counted per click.'
  }
}

// --------------------------------------------------------------------------
// 4. Section by section
// --------------------------------------------------------------------------

/** The page as the feed test describes it, with how many clickers reached and left each part. */
export function feedPageOutline(feed) {
  const page = isObj(feed?.landing) ? feed.landing : null
  const all = sessionsOf(feed)
  const ss = all.filter((s) => s.ad.click === true && isObj(s.landing))
  // older runs saved only per-ad totals: count from those instead of reporting zero clicks
  const totals = all.length ? [] : Object.values(isObj(feed?.summary?.per_creative) ? feed.summary.per_creative : {}).filter(isObj).map((m) => m.landing).filter(isObj)
  if (!page && !ss.length && !totals.length) return null
  if (!all.length && !totals.length) {
    return { sections: [{ key: 'load', title: 'Page load', detail: num(page?.load_seconds) != null ? `About ${page.load_seconds} s to load on a good connection` : '', reached: null, left: null, reachedPct: null }], clicks: null,
      note: 'This run saved the page but no visits, so there are no counts for it.' }
  }
  const sum = (k) => totals.reduce((t, r) => t + (num(r[k]) || 0), 0)
  const clicks = all.length ? ss.length : sum('clicks')
  const loaded = all.length ? ss.filter((s) => s.landing.loaded).length : sum('page_loaded')
  const read = ss.some((s) => 'read' in s.landing) ? ss.filter((s) => s.landing.read).length : null
  const started = all.length ? ss.filter((s) => s.landing.started_form).length : sum('form_started')
  const done = all.length ? ss.filter((s) => s.landing.completed).length : sum('converted')
  const out = [
    { key: 'load', title: 'Page load', detail: num(page?.load_seconds) != null ? `About ${page.load_seconds} s to load on a good connection` : '', reached: clicks, left: clicks ? clicks - loaded : null },
    { key: 'content', title: 'Page content', detail: [str(page?.shows), str(page?.price) && `Price shown: ${str(page.price)}`].filter(Boolean).join(' · '), reached: loaded, read, left: clicks ? loaded - started : null },
    { key: 'form', title: 'Signup form', detail: arr(page?.form_fields).length ? `Asks for ${arr(page.form_fields).join(', ')}${num(page?.steps) ? ` · ${page.steps} steps` : ''}` : '', reached: started, left: clicks ? started - done : null, finished: done }
  ]
  return { sections: out.map((s) => ({ ...s, reachedPct: clicks ? pct(s.reached, clicks) : null })), clicks,
    note: clicks ? `Out of ${clicks} simulated people who clicked an ad.` : 'No one clicked an ad, so no one reached the page.' }
}

/** The lab's scroll zones (older cro_lab.json) or the teardown's read depth (landing_teardown.json). */
export function scrollOutline(teardown) {
  if (!isObj(teardown)) return null
  const zones = arr(teardown.scroll_zones).filter(isObj)
  if (zones.length) {
    return {
      kind: 'zones', note: labNote(teardown),
      sections: zones.map((z, i) => {
        const kept = num(z.attention_retained_pct)
        const prev = i ? num(zones[i - 1].attention_retained_pct) : null
        return { key: `z${i}`, title: clean(z.zone).replace(/^Fold \d+ \([^)]*\):\s*/i, '') || `Part ${i + 1}`, where: (clean(z.zone).match(/^Fold \d+ \(([^)]*)\)/i) || [])[1] || '',
          detail: clean(z.focal_element), warning: clean(z.drop_off_warning).replace(/^none\b[\s—-]*/i, ''), keptPct: kept,
          dropPts: kept != null && prev != null ? Math.round((prev - kept) * 10) / 10 : null }
      })
    }
  }
  const ru = teardown.summary?.read_until
  if (isObj(ru) && ['top', 'middle', 'end'].some((k) => num(ru[k]?.k) != null)) {
    const k = (x) => num(ru[x]?.k) || 0
    const n = num(ru.top?.n) || k('top') + k('middle') + k('end')
    const reach = [n, k('middle') + k('end'), k('end')]
    const h1 = str(teardown.summary?.page?.h1) || str(teardown.summary?.page?.title)
    const titles = ['Top of the page', 'Middle of the page', 'End of the page']
    return {
      kind: 'depth', note: `How far ${n} simulated people said they would read. Simulated.`,
      sections: titles.map((title, i) => ({ key: ['top', 'middle', 'end'][i], title, detail: i === 0 && h1 ? `Headline: ${h1}` : '', reached: reach[i], keptPct: pct(reach[i], n),
        dropPts: i ? Math.round((pct(reach[i - 1], n) - pct(reach[i], n)) * 10) / 10 : null }))
    }
  }
  return null
}

/** The pages website-test visitors reached, in the order first seen. */
export function websitePages(web) {
  const order = [], seen = new Map()
  for (const v of arr(web?.sessions)) {
    const mine = new Set()
    for (const st of arr(v?.steps)) {
      const url = str(st?.url).replace(/#.*$/, '')
      const key = url || str(st?.title)
      if (!key || mine.has(key)) continue
      mine.add(key)
      let path = ''
      try { path = url ? new URL(url).pathname : '' } catch { path = url }
      if (!seen.has(key)) { seen.set(key, { key, title: str(st.title) || path || key, path, url, reached: 0 }); order.push(key) }
      seen.get(key).reached++
    }
  }
  const n = arr(web?.sessions).length
  return order.length ? { sections: order.map((k) => ({ ...seen.get(k), reachedPct: pct(seen.get(k).reached, n) })), visitors: n } : null
}

function labNote(teardown) {
  const calls = num(teardown?.usage?.calls)
  return calls === 0 ? 'From the conversion lab file. It records no model calls, so treat it as an estimate, not something the people did. Simulated.' : 'From the conversion lab. Simulated.'
}

// --------------------------------------------------------------------------
// 5. What to fix first
// --------------------------------------------------------------------------

/** "+14% Hero-to-Scroll Retention" -> {value: 14, unit: '%', what: 'hero-to-scroll retention', direction: 'up'} */
export function parseEstimate(text) {
  const t = clean(text)
  const m = t.match(/([+\-−–])?\s*(\d+(?:\.\d+)?)\s*(%|pts?|points?)?\s*(.*)$/i)
  if (!m) return t ? { text: t, value: null, direction: null } : null
  const neg = m[1] && m[1] !== '+'
  const value = Number(m[2]) * (neg ? -1 : 1)
  const what = m[4].replace(/^[\s:–-]+/, '').trim()
  return { text: t, value, unit: m[3] ? (m[3].startsWith('%') ? '%' : 'pts') : '', what, direction: value > 0 ? 'up' : value < 0 ? 'down' : null }
}

const LOWER_IS_BETTER = /abandon|drop|bounce|churn|cost|cpa|cac|friction|exit/i
export function estimateIsGood(est) {
  if (!est || est.direction == null) return null
  return LOWER_IS_BETTER.test(est.what || '') ? est.direction === 'down' : est.direction === 'up'
}

function causeMatch(text, causes) {
  const t = str(text)
  if (!t || !causes?.causes?.length) return null
  for (const c of causes.causes) {
    const g = REASON_GROUPS.find((x) => x.key === c.key)
    if (g && g.key !== 'form' && g.re.test(t)) return c
  }
  return null
}

/** Fixes and variants the conversion lab proposes, biggest saved estimate first. */
export function labFixes({ cro, teardown, whatif, causes } = {}) {
  const td = isObj(teardown) ? teardown : isObj(cro?.landing_teardown) ? cro.landing_teardown : null
  const wi = isObj(whatif) ? whatif : isObj(cro?.causal_whatif) ? cro.causal_whatif : null
  const out = []
  const push = (fix) => {
    const match = causeMatch([fix.title, fix.before, fix.after].join(' '), causes)
    if (match) fix.evidence.push(`Matches why ${match.count} of ${causes.total} people who left gave up: ${match.label.toLowerCase()}.`)
    out.push({ ...fix, id: `fix-${out.length}` })
  }
  if (td) {
    const note = labNote(td)
    for (const p of arr(td.sentiment_pins).filter(isObj)) {
      const est = parseEstimate(p.expected_lift)
      const ev = [note]
      if (num(p.score_0_10) != null) ev.unshift(`Lab score for this part: ${p.score_0_10} out of 10.`)
      push({ kind: 'copy', source: 'Landing teardown', title: clean(p.section) || 'Page change', before: clean(p.before_copy), after: clean(p.after_rewrite), estimate: est, good: estimateIsGood(est), evidence: ev })
    }
    for (const a of arr(td.top_cro_actions)) {
      const t = clean(a)
      if (t) push({ kind: 'action', source: 'Landing teardown', title: t, before: '', after: '', estimate: null, good: null, evidence: [note] })
    }
    const sum = td.summary
    for (const c of arr(sum?.confusing).filter(isObj)) {
      const share = c.share || {}
      const est = num(share.pct) != null ? { text: `${share.pct}% were confused about this`, value: share.pct, unit: '%', what: 'confused', direction: null } : null
      const ev = [`${c.count ?? share.k ?? '?'} of ${share.n ?? '?'} simulated people said this part was unclear${num(share.lo) != null ? ` (95% range ${share.lo}–${share.hi}%)` : ''}.`]
      push({ kind: 'clarity', source: 'Five-second test', title: `Make this clear: ${str(c.key).replace(/_/g, ' ')}`, before: '', after: '', estimate: est, good: null, evidence: ev, quotes: arr(c.quotes).slice(0, 2).map(str) })
    }
  }
  if (wi) {
    for (const a of arr(wi.attributes).filter((x) => isObj(x) && num(x.marginal_conv_lift_pts) != null)) {
      const v = a.marginal_conv_lift_pts
      const est = { text: `${v > 0 ? '+' : ''}${v} pts conversion`, value: v, unit: 'pts', what: 'conversion', direction: v > 0 ? 'up' : v < 0 ? 'down' : null }
      const ev = []
      if (num(a.card_dropoff_reduction_pts)) ev.push(`Lab estimate: ${a.card_dropoff_reduction_pts} pts fewer people leaving at the card step.`)
      ev.push('From the what-if model in the conversion lab. Simulated, not measured.')
      push({ kind: 'offer', source: 'What-if model', title: clean(a.label), before: '', after: '', estimate: est, good: estimateIsGood(est), evidence: ev })
    }
    for (const e of arr(wi.summary?.effects).filter((x) => isObj(x) && num(x.effect_pts) != null)) {
      const v = e.effect_pts
      const est = { text: `${v > 0 ? '+' : ''}${v} pts chance of being picked`, value: v, unit: 'pts', what: 'being picked', direction: v > 0 ? 'up' : v < 0 ? 'down' : null }
      const range = num(e.lo) != null ? `95% range ${e.lo > 0 ? '+' : ''}${e.lo} to ${e.hi > 0 ? '+' : ''}${e.hi} pts. ` : ''
      push({ kind: 'offer', source: 'What-if choice test', title: `${clean(e.attribute)}: ${clean(e.level)} instead of ${clean(e.versus)}`, before: clean(e.versus), after: clean(e.level), estimate: est, good: estimateIsGood(est),
        evidence: [`${range}${clean(e.verdict)}`.trim() || 'Simulated choices.', 'Simulated people choosing between versions.'] })
    }
  }
  const size = (f) => (f.estimate?.value != null ? Math.abs(f.estimate.value) : -1)
  return out.map((f, i) => ({ ...f, order: i })).sort((a, b) => size(b) - size(a) || a.order - b.order)
}

// --------------------------------------------------------------------------
// Prompts for the chat (they go through the agent's approval card; nothing runs from here)
// --------------------------------------------------------------------------

const cut = (s, n) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s)

export function fixPrompt(fix, run = {}) {
  const where = run.title ? `the simulated buyers from "${run.title}"${run.name && run.name !== run.title ? ` (${run.name})` : ''}` : 'the simulated buyers from this run'
  const change = fix.before && fix.after ? `change "${cut(fix.before, 200)}" to "${cut(fix.after, 200)}"` : `${cut(fix.title, 240)}`
  return `Test this landing page fix on ${where}: ${change}. Compare it with the current page and show me the cost before anything runs.`
}

export function landingTestPrompt(run = {}) {
  const who = run.title ? ` with the simulated buyers from "${run.title}"` : ''
  return `Help me test a landing page${who}. Ask me for the URL, the journey to try and the checks that confirm success, and show me the cost before anything runs.`
}

// --------------------------------------------------------------------------
// Everything for one run
// --------------------------------------------------------------------------

export function landingAnalysis({ feed = null, cro = null, teardown = null, whatif = null, web = null } = {}) {
  const funnel = feedFunnel(feed)
  const webFunnel = websiteFunnel(web)
  const causes = feedDropCauses(feed)
  const webCauses = websiteDropCauses(web)
  const ads = adLandingRows(feed)
  const td = isObj(teardown) ? teardown : isObj(cro?.landing_teardown) ? cro.landing_teardown : null
  const outline = {
    page: funnel ? feedPageOutline(feed) : null,
    scroll: scrollOutline(td),
    pages: websitePages(web)
  }
  const fixes = labFixes({ cro, teardown, whatif, causes })
  const hasData = Boolean(funnel || webFunnel || causes || webCauses || ads || outline.scroll || outline.pages || fixes.length)
  return { hasData, funnel, webFunnel, causes, webCauses, ads, outline, fixes, page: isObj(feed?.landing) ? feed.landing : null, website: isObj(web) ? { url: str(web.url), goal: str(web.goal), interpretation: str(web.interpretation) } : null }
}
