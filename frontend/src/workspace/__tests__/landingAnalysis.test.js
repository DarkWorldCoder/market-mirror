import test from 'node:test'
import assert from 'node:assert/strict'
import {
  adLandingRows, estimateIsGood, feedDropCauses, feedFunnel, feedPageOutline, fixPrompt, isSystemReason, labFixes, landingAnalysis, landingFilesIn,
  landingTestPrompt, parseEstimate, quoteExists, reasonGroup, savedTexts, scrollOutline, websiteDropCauses, websiteFunnel, websitePages
} from '../landingAnalysis.js'

const ad = (extra = {}) => ({ noticed: true, click: false, thought: '', ...extra })
const session = (id, creative, adExtra, landing) => ({ agent_id: id, name: `Person ${id}`, segment: 'Students', country: 'India', creative_id: creative, ad: ad(adExtra), ...(landing ? { landing } : {}) })
const feed = {
  creatives: [{ id: 'a', name: 'Kids nap ad', platform: 'facebook' }, { id: 'b', name: 'Commute ad', platform: 'instagram' }],
  landing: { shows: 'A page with a Start free trial button', price: '7 days free, then USD 4.99 per month', load_seconds: 2.5, form_fields: ['email', 'card number'], steps: 2 },
  sessions: [
    session(1, 'a', { noticed: false }),
    session(2, 'a', {}),
    session(3, 'a', { click: true }, { loaded: false, read: false, started_form: false, completed: false, friction_gate: 'network_timeout', drop_reason: 'left before the page loaded (7.5s on 3g)' }),
    session(4, 'a', { click: true }, { loaded: true, read: true, started_form: true, completed: true, drop_reason: '', thought: 'Fast page, I am in.' }),
    session(5, 'a', { click: true }, { loaded: true, read: true, started_form: true, completed: false, friction_gate: 'form_abandon', drop_reason: 'Card details upfront for a free trial felt like too much.', thought: 'Hmm, card again.' }),
    session(6, 'b', { click: true }, { loaded: true, read: true, started_form: false, completed: false, friction_gate: 'form_abandon', drop_reason: 'The price in dollars is more than I would pay.', thought: 'Too pricey.' }),
    session(7, 'b', { click: true }, { loaded: true, read: true, started_form: true, completed: false, friction_gate: 'form_abandon', drop_reason: 'gave up when the form showed an error or asked for a code', thought: 'Trying it now!' }),
    session(8, 'b', { click: true }, { loaded: true, read: true, started_form: true, completed: false, friction_gate: 'form_abandon', drop_reason: 'They want my credit card before I can try it.', thought: '' })
  ],
  summary: { per_creative: { a: { impressions: 5, landing: { clicks: 3 } }, b: { impressions: 3, landing: { clicks: 3 } } } }
}

test('lists the landing files a run has saved', () => {
  assert.deepEqual(landingFilesIn(['summary.json', 'feed_test.json', 'cro_lab.json', 'website_test.json']), ['feed_test.json', 'cro_lab.json', 'website_test.json'])
  assert.deepEqual(landingFilesIn(undefined), [])
})

test('funnel counts every step from the sessions, with the drop from the step before', () => {
  const f = feedFunnel(feed)
  assert.deepEqual(f.steps.map((s) => [s.key, s.n]), [['shown', 8], ['noticed', 7], ['clicked', 6], ['loaded', 5], ['read', 5], ['started', 4], ['converted', 1]])
  const started = f.steps.find((s) => s.key === 'started')
  assert.equal(started.keptPct, 80)
  assert.equal(started.dropPct, 20)
  assert.equal(started.lost, 1)
  assert.equal(f.steps[0].keptPct, null)
  assert.equal(f.ordered, true)
})

test('older runs fall back to the per-ad totals; no landing data means no funnel', () => {
  const old = { summary: { per_creative: { a: { impressions: 100, landing: { clicks: 4, page_loaded: 3, form_started: 2, converted: 1 } }, b: { impressions: 50 } } } }
  assert.deepEqual(feedFunnel(old).steps.map((s) => s.n), [150, 4, 3, 2, 1])
  assert.equal(feedFunnel({ sessions: [session(1, 'a', {})] }), null)
  assert.equal(feedFunnel(null), null)
})

test('system-written reasons are recognised and never shown as quotes', () => {
  assert.ok(isSystemReason('left before the page loaded (7.5s on 3g)'))
  assert.ok(isSystemReason('price (USD 4.99) exceeds comfortable discretionary budget (USD 3)'))
  assert.ok(!isSystemReason('Card details upfront felt like too much.'))
  assert.equal(reasonGroup('', 'network_timeout').key, 'slow')
  assert.equal(reasonGroup('They want my credit card first').key, 'card')
  assert.equal(reasonGroup('nothing in particular').key, 'other')
})

test('why people left: ranked causes, shares of the people with a reason, quotes only from saved words', () => {
  const c = feedDropCauses(feed)
  assert.equal(c.left, 5)
  assert.equal(c.total, 5)
  assert.equal(c.method, 'rules')
  assert.deepEqual(c.stages.map((s) => [s.key, s.n]), [['before_load', 1], ['page', 1], ['form', 3]])
  assert.deepEqual(c.causes.map((x) => [x.key, x.count]), [['card', 2], ['slow', 1], ['price', 1], ['form_error', 1]])
  assert.equal(c.causes[0].sharePct, 40)
  const saved = savedTexts(feed)
  for (const cause of c.causes) for (const q of cause.quotes) assert.ok(saved.has(q.text), q.text)
  assert.deepEqual(c.causes[0].quotes.map((q) => q.text), ['Card details upfront for a free trial felt like too much.', 'They want my credit card before I can try it.'])
  assert.equal(c.causes[0].quotes[0].who, 'Person 5 · Students · India')
  // the page-load drop has no words of its own: the recorded event is shown, not a quote
  const slow = c.causes.find((x) => x.key === 'slow')
  assert.deepEqual(slow.quotes, [])
  assert.deepEqual(slow.events, ['left before the page loaded (7.5s on 3g)'])
  // the forced form error keeps the person's own thought, marked as a thought
  const err = c.causes.find((x) => x.key === 'form_error')
  assert.deepEqual(err.quotes, [{ text: 'Trying it now!', who: 'Person 7 · Students · India', kind: 'thought' }])
})

test('Jev causes are used when saved, and an example that is not in the data is dropped', () => {
  const withJev = { ...feed, drop_causes: { labelled: 4, reasons: 5, overall: [
    { cause: 'payment_friction', count: 3, share_pct: 75, examples: ['They want my credit card before I can try it.', 'An invented sentence nobody wrote.'] },
    { cause: 'slow_page', count: 1, share_pct: 25, examples: ['left before the page loaded (7.5s on 3g)'] }
  ] } }
  const c = feedDropCauses(withJev)
  assert.equal(c.method, 'jev')
  assert.equal(c.causes[0].label, 'Payment friction')
  assert.deepEqual(c.causes[0].quotes.map((q) => q.text), ['They want my credit card before I can try it.'])
  assert.deepEqual(c.causes[1].quotes, [])
  assert.deepEqual(c.causes[1].events, ['left before the page loaded (7.5s on 3g)'])
  assert.match(c.note, /4 of 5 reasons/)
  assert.ok(!quoteExists('An invented sentence nobody wrote.', savedTexts(withJev)))
})

test('per-ad comparison names a leader only when one ad is ahead', () => {
  const r = adLandingRows(feed)
  assert.deepEqual(r.rows.map((x) => [x.id, x.clicks, x.loaded, x.started, x.converted]), [['a', 3, 2, 2, 1], ['b', 3, 3, 2, 0]])
  assert.equal(r.leader, 'a')
  assert.match(r.leaderText, /Kids nap ad sent the most people who signed up \(1 of 3/)
  assert.match(r.note, /fewer than 10 clicks/)
  const tie = { sessions: [
    session(1, 'a', { click: true }, { loaded: true, started_form: false, completed: false }),
    session(2, 'b', { click: true }, { loaded: true, started_form: false, completed: false })
  ] }
  assert.equal(adLandingRows(tie).leader, null)
  assert.equal(adLandingRows({ sessions: [feed.sessions[3]] }), null)
})

test('page outline: how many clickers reached and left the load, the content and the form', () => {
  const o = feedPageOutline(feed)
  assert.deepEqual(o.sections.map((s) => [s.key, s.reached, s.left]), [['load', 6, 1], ['content', 5, 1], ['form', 4, 3]])
  assert.equal(o.sections[2].finished, 1)
  assert.match(o.sections[2].detail, /Asks for email, card number · 2 steps/)
  assert.match(o.sections[1].detail, /Price shown: 7 days free/)
})

test('scroll outline reads the lab zones or the teardown read depth', () => {
  const zones = scrollOutline({ usage: { calls: 0 }, scroll_zones: [
    { zone: 'Fold 1 (0–20%): Hero', attention_retained_pct: 100, focal_element: 'H1', drop_off_warning: 'None — all see it' },
    { zone: 'Fold 2 (20–40%): Proof', attention_retained_pct: 60, focal_element: 'Reviews', drop_off_warning: '⚠️ 40% leave here' }
  ] })
  assert.equal(zones.kind, 'zones')
  assert.deepEqual(zones.sections.map((s) => [s.title, s.where, s.keptPct, s.dropPts]), [['Hero', '0–20%', 100, null], ['Proof', '20–40%', 60, 40]])
  assert.equal(zones.sections[1].warning, '40% leave here')
  assert.match(zones.note, /no model calls/)
  const depth = scrollOutline({ summary: { page: { h1: 'Fit in 15' }, read_until: { top: { k: 5, n: 10 }, middle: { k: 3, n: 10 }, end: { k: 2, n: 10 } } } })
  assert.deepEqual(depth.sections.map((s) => [s.key, s.reached, s.keptPct, s.dropPts]), [['top', 10, 100, null], ['middle', 5, 50, 50], ['end', 2, 20, 30]])
  assert.equal(depth.sections[0].detail, 'Headline: Fit in 15')
  assert.equal(scrollOutline({}), null)
})

const web = {
  url: 'http://127.0.0.1:4000', goal: 'add_to_cart', goal_check: 'cart_added', checks: [{ name: 'product_visible' }, { name: 'cart_added' }],
  summary: { visitors: 3, goal_observed: 1, left: 1 }, milestones: { product_visible: 2, cart_added: 1 },
  sessions: [
    { name: 'Asha', segment: 'Runner', status: 'goal_observed', steps: [{ url: 'http://127.0.0.1:4000/', title: 'Shop', action: { action: 'click', reason: 'Fits my budget.' } }, { url: 'http://127.0.0.1:4000/cart', title: 'Cart' }] },
    { name: 'Mira', segment: 'Budget', status: 'left', steps: [{ url: 'http://127.0.0.1:4000/', title: 'Shop', action: { action: 'leave', reason: 'The shoes cost $50, over my $10 budget.' } }] },
    { name: 'Kai', segment: 'Budget', status: 'blocked', stop_reason: 'cross-origin checkout', steps: [] }
  ]
}

test('website journeys: milestone counts, how visits ended, the pages reached', () => {
  const f = websiteFunnel(web)
  assert.equal(f.ordered, false)
  assert.deepEqual(f.steps.map((s) => [s.label, s.n]), [['Visitors started', 3], ['Check passed: product visible', 2], ['Check passed: cart added', 1]])
  const c = websiteDropCauses(web)
  assert.deepEqual(c.causes.map((x) => [x.key, x.count]), [['left', 1], ['blocked', 1]])
  assert.deepEqual(c.causes[0].quotes, [{ text: 'The shoes cost $50, over my $10 budget.', who: 'Mira · Budget · Shop', kind: 'reason' }])
  assert.deepEqual(c.causes[1].events, ['cross-origin checkout'])
  const p = websitePages(web)
  assert.deepEqual(p.sections.map((s) => [s.path, s.reached]), [['/', 2], ['/cart', 1]])
  assert.equal(websiteFunnel(null), null)
})

test('estimates are parsed with their direction; lower is better for abandonment', () => {
  assert.deepEqual(parseEstimate('+22% CTA Click-Through Rate'), { text: '+22% CTA Click-Through Rate', value: 22, unit: '%', what: 'CTA Click-Through Rate', direction: 'up' })
  const drop = parseEstimate('−38% Form Abandonment (Say-vs-Do Gap)')
  assert.equal(drop.value, -38)
  assert.equal(estimateIsGood(drop), true)
  assert.equal(estimateIsGood(parseEstimate('-5% conversion')), false)
  assert.equal(parseEstimate(''), null)
})

test('fixes come biggest estimate first, with matching drop causes as evidence', () => {
  const cro = {
    landing_teardown: { usage: { calls: 0 },
      sentiment_pins: [
        { section: 'Hero', before_copy: 'Old headline', after_rewrite: 'New headline', expected_lift: '+14% Hero retention', score_0_10: 8.4 },
        { section: 'Signup form', before_copy: 'Card number field', after_rewrite: 'Phone only', expected_lift: '−38% Form Abandonment' }
      ],
      top_cro_actions: ['Add reviews under the button'] },
    causal_whatif: { attributes: [{ label: 'No-card trial', marginal_conv_lift_pts: 11.4, card_dropoff_reduction_pts: 34 }] }
  }
  const causes = feedDropCauses(feed)
  const fixes = labFixes({ cro, causes })
  assert.deepEqual(fixes.map((f) => f.title), ['Signup form', 'Hero', 'No-card trial', 'Add reviews under the button'])
  assert.equal(fixes[0].good, true)
  assert.ok(fixes[0].evidence.some((e) => /Matches why 2 of 5 people who left gave up: asked for card details up front/.test(e)))
  assert.ok(fixes[1].evidence.some((e) => /no model calls/.test(e)))
  assert.equal(fixes[3].estimate, null)
  // newer envelopes: confusing parts and choice-test effects
  const newer = labFixes({
    teardown: { engine: 'teardown', summary: { confusing: [{ key: 'price', count: 4, share: { k: 4, n: 10, pct: 40, lo: 17, hi: 69 }, quotes: ['Is it monthly?'] }] } },
    whatif: { engine: 'whatif', summary: { effects: [{ attribute: 'Trial', level: '14 days', versus: '7 days', effect_pts: 6, lo: 1, hi: 11, verdict: 'likely helps' }] } }
  })
  assert.deepEqual(newer.map((f) => f.title), ['Make this clear: price', 'Trial: 14 days instead of 7 days'])
  assert.deepEqual(newer[0].quotes, ['Is it monthly?'])
  assert.match(newer[1].evidence[0], /95% range \+1 to \+11 pts/)
})

test('chat prompts ask for the cost first and never claim results', () => {
  const p = fixPrompt({ title: 'Signup form', before: 'Card number field', after: 'Phone only' }, { title: 'Fitloop', name: 'fitloop_1000' })
  assert.equal(p, 'Test this landing page fix on the simulated buyers from "Fitloop" (fitloop_1000): change "Card number field" to "Phone only". Compare it with the current page and show me the cost before anything runs.')
  assert.match(fixPrompt({ title: 'Add reviews' }), /from this run: Add reviews\. .*show me the cost before anything runs\.$/)
  assert.match(landingTestPrompt({ title: 'Fitloop' }), /^Help me test a landing page with the simulated buyers from "Fitloop"\. .*before anything runs\.$/)
})

test('a run without landing data has nothing to show', () => {
  assert.equal(landingAnalysis({ feed: { sessions: [session(1, 'a', {})] } }).hasData, false)
  assert.equal(landingAnalysis({}).hasData, false)
  const full = landingAnalysis({ feed, web })
  assert.equal(full.hasData, true)
  assert.ok(full.funnel && full.webFunnel && full.causes && full.webCauses && full.ads && full.outline.page && full.outline.pages)
})

test('visitors started counts the session records, zero when none started', () => {
  const stopped = { summary: { visitors: 4 }, sessions: [{ started: false }, { started: false }] }
  assert.equal(websiteFunnel(stopped).steps[0].n, 0)
  // without session records the summary is used
  assert.equal(websiteFunnel({ summary: { visitors: 4 } }).steps[0].n, 4)
})

test('the leader sentence names the score that decided it', () => {
  const tiedSignups = { sessions: [
    session(1, 'a', { click: true }, { loaded: true, started_form: true, completed: true }),
    session(2, 'a', { click: true }, { loaded: true, started_form: true, completed: false }),
    session(3, 'b', { click: true }, { loaded: true, started_form: true, completed: true }),
    session(4, 'b', { click: true }, { loaded: true, started_form: false, completed: false })
  ] }
  const r = adLandingRows(tiedSignups)
  assert.equal(r.leader, 'a')
  assert.doesNotMatch(r.leaderText, /most people who signed up/)
  assert.match(r.leaderText, /^Signups are tied at 1; a had the most people start signup \(2 of 2 who clicked\)\.$/)
})

test('page outline uses the per-ad totals when an older run saved no sessions', () => {
  const legacy = { landing: { shows: 'A page' }, summary: { per_creative: { a: { impressions: 50, landing: { clicks: 4, page_loaded: 3, form_started: 2, converted: 1 } } } } }
  const o = feedPageOutline(legacy)
  assert.equal(o.clicks, 4)
  assert.deepEqual(o.sections.map((s) => [s.key, s.reached, s.left]), [['load', 4, 1], ['content', 3, 1], ['form', 2, 1]])
  assert.match(o.note, /Out of 4 simulated people/)
  assert.equal(landingAnalysis({ feed: legacy }).outline.page.clicks, 4)
})
