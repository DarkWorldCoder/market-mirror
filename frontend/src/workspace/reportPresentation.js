const reports = {
 'summary.json': ['Experiment overview', 'Results'], 'market_report.md': ['Market research report', 'Results'], 'report.md': ['Research narrative', 'Results'],
 'survey.json': ['Buyer survey', 'Buyer research'], 'thought_stream.json': ['Buyer reasoning', 'Buyer research'], 'feed_story.json': ['Social conversations', 'Buyer research'], 'analyst_panel.json': ['Analyst perspectives', 'Buyer research'], 'questionnaire.json': ['Questionnaire responses', 'Buyer research'], 'focus_group.json': ['Focus group discussion', 'Buyer research'],
 'feed_test.json': ['Ad creative comparison', 'Advertising'], 'feed_test_creatives.csv': ['Creative performance', 'Advertising'], 'feed_test_sessions.csv': ['Individual feed sessions', 'Advertising'], 'ad_patterns.json': ['Creative patterns', 'Advertising'], 'ideas.json': ['Creative ideas', 'Advertising'],
 'pitch.json': ['Sales pitch reactions', 'Strategy'], 'email_test.json': ['Email campaign results', 'Strategy'], 'choice_test.json': ['Preference study', 'Strategy'], 'campaign_plan.json': ['Campaign plan', 'Strategy'],
 'config.json': ['Audience profiles', 'Audience'], 'graph.json': ['Audience network', 'Audience'], 'agent_stats.json': ['Persona activity', 'Activity'], 'timeline.json': ['Activity over time', 'Activity'], 'actions.json': ['Recorded actions', 'Activity'],
 'backtest.json': ['Comparison with real results', 'Validation'], 'calibration.json': ['Calibration results', 'Validation'], 'real_check.csv': ['Questions for real customers', 'Validation'],
 'dashboard.html': ['Standalone dashboard', 'Results'], 'disclosure.md': ['Study methodology', 'Methodology'], 'usage.json': ['Model usage', 'Usage'], 'run_manifest.json': ['Run metadata', 'Advanced'], 'ontology.json': ['Graph schema', 'Advanced'],
}
export const readableLabel = value => String(value).replace(/([a-z])([A-Z])/g, '$1 $2').replace(/_/g, ' ').replace(/\b(?:id|ids|api|crm|csv|json|url|llm|ssr|ctr|cpa|roas)\b/gi, word => word.toUpperCase()).replace(/^./, char => char.toUpperCase())
export function reportInfo(file) {
 const known = reports[file]
 const title = known?.[0] || readableLabel(String(file).replace(/\.[^.]+$/, '').replaceAll('-', ' '))
 const category = known?.[1] || (/^(posts|comments)_/.test(file) ? 'Buyer research' : /usage|cost|spend/.test(file) ? 'Usage' : /manifest|config|log|ontology|provenance/.test(file) ? 'Advanced' : 'Other reports')
 return { file, title, category }
}
export function preferredReport(files = []) { return ['summary.json', 'market_report.md', 'report.md', 'survey.json', 'feed_test.json'].find(file => files.includes(file)) || files.find(file => reportInfo(file).category !== 'Advanced') || files[0] || '' }
export function tableRows(value) {
 if (!Array.isArray(value) || !value.length) return null
 if (value.every(row => Array.isArray(row) && row.length === 2 && typeof row[0] === 'string' && typeof row[1] === 'number')) return value.map(([label, count]) => ({ label, count }))
 return value.every(row => row && typeof row === 'object' && !Array.isArray(row)) ? value : null
}

// ---------------------------------------------------------------------------------------------------------------
// Reports a marketer can read: each known file becomes a plain title, one sentence on what it tells you, key
// numbers as labelled cards and readable sections (summaries, lists, people or analyst cards, ranked bars, quotes).
// Plumbing fields (material counts, ids, paths, timings, token usage) are left for the collapsed technical view.
// Every number here comes from simulated people.

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const pct = (v) => (num(v) === null ? null : `${Math.round(v * 10) / 10}%`)
const text = (v) => (v === null || v === undefined ? '' : String(v)).trim()
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s)
const plain = (s) => cap(text(s).replaceAll('_', ' '))
const card = (label, value, note = '') => (value === null || value === undefined || value === '' ? null : { label, value: String(value), note })
const compact = (list) => list.filter(Boolean)
const votes = (v) => (v && typeof v === 'object' ? Object.entries(v).map(([k, n]) => `${plain(k)} ${n}`).join(' · ') : '')

function fromSummary(d) {
  const mk = d.marketing || {}, o = mk.overall || {}, dec = d.decision || {}
  const segments = (mk.by_segment || []).map((s) => ({ label: s.key || s.segment, value: num(s.expected_convert_yes) ?? num(s.convert_yes) ?? 0, note: s.n ? `n=${s.n}` : '' }))
  return {
    intro: 'The overall verdict for this experiment and how each audience responded.',
    cards: compact([card('Decision', plain(dec.decision)), card('Simulated people', mk.people ?? d.agents), card('Would buy', pct(o.convert_yes)), card('Maybe', pct(o.convert_maybe)), card('Would not', pct(o.convert_no))]),
    sections: compact([
      dec.summary && { type: 'summary', title: 'In one line', text: dec.summary },
      segments.length && { type: 'bars', title: 'Would buy, by audience', unit: '%', rows: segments.sort((a, b) => b.value - a.value) },
      (mk.objections || []).length && { type: 'bars', title: 'Why people said no', unit: '%', rows: mk.objections.map((x) => ({ label: x.label, value: num(x.share) ?? 0 })) },
      (mk.objections || []).some((x) => x.examples?.length) && { type: 'quotes', title: 'In their words', items: mk.objections.flatMap((x) => (x.examples || []).slice(0, 1)).slice(0, 4).map((e) => ({ text: e.text, who: [e.name, e.segment].filter(Boolean).join(' · ') })) }
    ])
  }
}
function fromSurvey(d) {
  const rows = Array.isArray(d.responses) ? d.responses : []
  const tally = {}
  for (const r of rows) { const v = text(r.answer?.would_convert).toLowerCase(); if (v) tally[v] = (tally[v] || 0) + 1 }
  const total = Object.values(tally).reduce((a, b) => a + b, 0) || 1
  return {
    intro: 'What each simulated buyer said when asked about the offer: would they buy, and why or why not.',
    cards: compact([card('Answers', rows.length), card('Offer', text(d.offer).slice(0, 60)), card('Goal', text(d.goal).slice(0, 60))]),
    sections: compact([
      Object.keys(tally).length && { type: 'bars', title: 'Would they buy?', unit: '%', rows: Object.entries(tally).map(([k, n]) => ({ label: plain(k), value: Math.round((n / total) * 1000) / 10, note: `${n} people` })) },
      { type: 'quotes', title: 'What they said', items: rows.filter((r) => r.answer?.quote).slice(0, 6).map((r) => ({ text: r.answer.quote, who: [r.name, r.answer.would_convert ? `would buy: ${r.answer.would_convert}` : ''].filter(Boolean).join(' · ') })) },
      { type: 'list', title: 'Main objections', items: rows.map((r) => text(r.answer?.main_objection)).filter(Boolean).slice(0, 6) }
    ])
  }
}
function fromAnalysts(d) {
  const c = d.consensus || {}
  const analysts = (d.analysts || []).map((a) => {
    const r = a.result || {}
    return { title: r.lens || a.lens || a.id, subtitle: a.id, badge: r.verdict ? plain(r.verdict) : a.error ? 'Failed' : '', body: r.headline || r.summary || a.error || '',
      bullets: compact([r.best_audience && `Best audience: ${r.best_audience}`, r.best_message && `Best message: ${r.best_message}`, num(r.confidence) !== null && `Confidence: ${r.confidence}/10`, r.evidence_gaps && `Missing evidence: ${r.evidence_gaps}`]) }
  })
  return {
    intro: `${analysts.length} simulated analysts, each with a different lens, read the run and gave a verdict. Where they agree is shown first.`,
    cards: compact([card('Verdict', plain(c.verdict?.winner), c.verdict?.agreement != null ? `${c.verdict.agreement}% agree` : ''), card('Chance of success', pct(c.success_probability)), card('Average confidence', num(c.confidence_mean) !== null ? `${c.confidence_mean}/10` : null), card('Agreement', plain(c.consensus))]),
    sections: compact([
      d.brief && { type: 'summary', title: 'The question they answered', text: d.brief },
      (c.best_audience || c.best_message) && { type: 'summary', title: 'Where they agree', highlight: true,
        text: compact([c.best_audience?.winner && `Best audience: ${c.best_audience.winner} (${c.best_audience.agreement}% agree)`, c.best_message?.winner && `Best message: ${c.best_message.winner} (${c.best_message.agreement}% agree)`, c.verdict && `Votes: ${votes(c.verdict.votes)}`]).join('\n') },
      analysts.length && { type: 'cards', title: 'Each analyst', items: analysts },
      (c.themes || []).length && { type: 'bars', title: 'Themes they raised', unit: '%', rows: c.themes.map((t) => ({ label: t.theme, value: num(t.share) ?? 0, note: t.analysts ? `${t.analysts} analysts` : '' })) }
    ])
  }
}
function fromActionPlan(d) {
  return {
    intro: 'What to change and what to run next, written from the simulated results.',
    cards: [],
    sections: compact([
      (d.fixes || []).length && { type: 'list', title: 'Fix first', items: d.fixes },
      (d.messages_to_use || []).length && { type: 'list', title: 'Messages to use', items: d.messages_to_use },
      (d.ads || []).length && { type: 'cards', title: 'Ads to run', items: d.ads.map((a) => ({ title: a.creative_id, subtitle: (a.platforms || []).join(', '), body: a.why, bullets: compact([a.audience && `Audience: ${a.audience}`, a.budget && `Budget: ${a.budget}`, a.duration && `Run for: ${a.duration}`]) })) },
      d.retest && { type: 'summary', title: 'Then retest', highlight: true, text: compact([d.retest.what, d.retest.when && `When: ${d.retest.when}`, d.retest.success_looks_like && `Success looks like: ${d.retest.success_looks_like}`]).join('\n') }
    ])
  }
}
function fromMarketReport(d) {
  const s = d.sections || {}, ex = s.executive_summary || {}
  const fromPlan = d.action_plan ? fromActionPlan(d.action_plan).sections : []
  return {
    intro: 'The full market report in short: the decision, why, and what to do next.',
    cards: compact([card('Decision', plain(ex.decision)), card('Recommended price', s.pricing?.recommended_price), card('Confidence', plain(s.limits?.confidence))]),
    sections: compact([
      ex.headline && { type: 'summary', title: 'Headline', highlight: true, text: ex.headline },
      (ex.bullets || []).length && { type: 'list', title: 'Key points', items: ex.bullets },
      s.survey_results?.summary && { type: 'summary', title: 'Buyer survey', text: compact([s.survey_results.summary, s.survey_results.best_audience && `Best audience: ${s.survey_results.best_audience}`, s.survey_results.weakest_audience && `Weakest: ${s.survey_results.weakest_audience}`]).join('\n') },
      (s.objections || []).length && { type: 'bars', title: 'Top objections', unit: '%', rows: s.objections.map((o) => ({ label: o.objection, value: num(o.share_pct) ?? 0 })) },
      (s.objections || []).some((o) => o.quote) && { type: 'quotes', title: 'In their words', items: s.objections.filter((o) => o.quote).slice(0, 4).map((o) => ({ text: o.quote, who: o.who || '' })) },
      s.ad_results?.summary && { type: 'summary', title: 'Ads', text: compact([s.ad_results.summary, s.ad_results.winner && `Winner: ${s.ad_results.winner}`]).join('\n') },
      s.pricing?.summary && { type: 'summary', title: 'Pricing', text: compact([s.pricing.summary, s.pricing.range && `Range: ${s.pricing.range}`]).join('\n') },
      s.social?.summary && { type: 'summary', title: 'On social media', text: s.social.summary },
      ...fromPlan,
      (s.limits?.caveats || []).length && { type: 'list', title: 'Limits to keep in mind', items: s.limits.caveats }
    ])
  }
}
function fromPitch(d) {
  return {
    intro: 'How simulated buyers reacted to the sales pitch, which objections came up and whether the rebuttals worked.',
    cards: compact([card('Pitch score', num(d.pitch_score) !== null ? `${d.pitch_score}/100` : null), card('People pitched', d.people_pitched), card('Answered', d.answered), card('Hot leads', (d.hot_leads || []).length || null)]),
    sections: compact([
      (d.objections || []).length && { type: 'bars', title: 'Objections raised', unit: '%', rows: d.objections.map((o) => ({ label: plain(o.type), value: num(o.share) ?? 0, note: num(o.rebuttal_success) !== null ? `rebuttal worked ${Math.round(o.rebuttal_success)}%` : '' })) },
      (d.by_segment || []).length && { type: 'bars', title: 'Said yes, by audience', unit: '%', rows: d.by_segment.map((s) => ({ label: s.segment, value: num(s.yes) ?? 0, note: s.n ? `n=${s.n}` : '' })) },
      (d.best_replies || []).length && { type: 'quotes', title: 'Best replies', items: d.best_replies.map((r) => ({ text: r.text, who: [r.name, r.segment].filter(Boolean).join(' · ') })) },
      (d.fixes || []).length && { type: 'list', title: 'What to fix in the pitch', items: d.fixes },
      (d.hot_leads || []).length && { type: 'cards', title: 'Warmest leads', items: d.hot_leads.slice(0, 6).map((l) => ({ title: l.name, subtitle: l.segment, badge: plain(l.verdict), body: l.next_step, bullets: compact([num(l.lead_score) !== null && `Lead score ${l.lead_score}`, l.reach && `Reach: ${l.reach}`]) })) }
    ])
  }
}
function fromIdeas(d) {
  return {
    intro: 'Next tests worth running, each with the evidence behind it and how to tell if it worked.',
    cards: compact([card('Ideas', (d.ideas || []).length)]),
    sections: compact([(d.ideas || []).length && { type: 'cards', title: 'Ideas', items: d.ideas.map((i) => ({ title: i.title, subtitle: [i.platform, i.type].filter(Boolean).join(' · '), badge: plain(i.priority), body: i.hypothesis, bullets: compact([i.audience && `Audience: ${i.audience}`, i.budget && `Budget: ${i.budget}`, i.duration && `Run for: ${i.duration}`, i.success_looks_like && `Success looks like: ${i.success_looks_like}`]) })) }])
  }
}
function fromFeedTest(d) {
  const per = d.summary?.per_creative || {}
  const names = Object.fromEntries((d.creatives || []).map((c) => [c.id, c.name || c.id]))
  const rows = Object.entries(per).filter(([, v]) => num(v?.expected_ctr) !== null).map(([id, v]) => ({ label: names[id] || id, value: v.expected_ctr, note: v.impressions ? `${v.impressions} views` : '' }))
  return {
    intro: 'Each ad was shown inside realistic simulated feeds. This compares how often people would click.',
    cards: compact([card('Ads tested', (d.creatives || []).length), card('People', d.personas_tested), card('Views', d.exposures)]),
    sections: compact([
      rows.length && { type: 'bars', title: 'Expected click-through per ad', unit: '%', rows: rows.sort((a, b) => b.value - a.value) },
      (d.creatives || []).length && { type: 'cards', title: 'The ads', items: d.creatives.map((c) => ({ title: c.name || c.id, subtitle: plain(c.platform), body: c.headline || c.text, bullets: compact([c.cta && `Button: ${c.cta}`, (c.segments || []).length && `Aimed at: ${c.segments.join(', ')}`]) })) }
    ])
  }
}
function fromAgentStats(d) {
  const rows = (Array.isArray(d) ? d : d.agents || []).filter((a) => num(a.total_actions) !== null)
  return {
    intro: 'How active each simulated person was on the simulated social sites.',
    cards: compact([card('People', rows.length), card('Actions in total', rows.reduce((t, a) => t + a.total_actions, 0))]),
    sections: compact([rows.length && { type: 'bars', title: 'Most active people', unit: '', rows: [...rows].sort((a, b) => b.total_actions - a.total_actions).slice(0, 15).map((a) => ({ label: a.agent_name || `Person ${a.agent_id}`, value: a.total_actions, note: compact([a.twitter_actions && `${a.twitter_actions} feed`, a.reddit_actions && `${a.reddit_actions} forum`]).join(' · ') })) }])
  }
}
function fromConfig(d) {
  const people = (d.persona_index || []).filter((p) => (p.kind || 'persona') === 'persona')
  const bySeg = {}
  for (const p of people) bySeg[p.segment || 'No segment'] = (bySeg[p.segment || 'No segment'] || 0) + 1
  return {
    intro: 'Who took part: the invented people, grouped by audience. No real person is represented.',
    cards: compact([card('Simulated people', people.length), card('Audiences', Object.keys(bySeg).length)]),
    sections: compact([
      people.length && { type: 'bars', title: 'People per audience', unit: '', rows: Object.entries(bySeg).sort((a, b) => b[1] - a[1]).map(([label, value]) => ({ label, value })) },
      people.length && { type: 'cards', title: 'A few of them', items: people.slice(0, 6).map((p) => ({ title: p.name, subtitle: compact([p.age && `${p.age}`, p.occupation, [p.city, p.country].filter(Boolean).join(', ')]).join(' · '), badge: p.segment, body: p.decision_role || p.platform_habits || '' })) }
    ])
  }
}

const PRESENTERS = { 'summary.json': fromSummary, 'survey.json': fromSurvey, 'analyst_panel.json': fromAnalysts, 'action_plan.json': fromActionPlan, 'market_report.json': fromMarketReport, 'pitch.json': fromPitch, 'ideas.json': fromIdeas, 'feed_test.json': fromFeedTest, 'agent_stats.json': fromAgentStats, 'config.json': fromConfig }

/** A readable version of a saved report, or null when the file has no dedicated layout (the generic view is used). */
export function presentReport(file, data) {
  const fn = PRESENTERS[file]
  if (!fn || !data || typeof data !== 'object') return null
  try {
    const out = fn(data)
    out.sections = (out.sections || []).filter((s) => s && (s.type !== 'list' || s.items?.length) && (s.type !== 'quotes' || s.items?.length) && (s.type !== 'cards' || s.items?.length))
    return out.cards.length || out.sections.length ? out : null
  } catch {
    return null
  }
}

/** Keys that are plumbing for a reader: counts of material sent to models, ids, paths, timings, usage. */
export const technicalKey = (key) => /(^id$|_ids?$|^ids$|^run_dir$|^output_dir$|^out_dir$|^file_path$|_path$|^base_url$|_status$|^generated_at$|^created_at$|^updated_at$|^started_at$|^finished_at$|^asked_at$|^simulation_requirement$|^has_|^files$|^file_paths$|^material_|^usage$|_tokens$|^method$|^model$|^provider$|^seed$|^raw$|^timing|^elapsed|^duration_ms$|^version$)/.test(String(key))
