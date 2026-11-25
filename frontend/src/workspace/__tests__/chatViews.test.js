import test from 'node:test'
import assert from 'node:assert/strict'
import { CHAT_VIEWS, INSIGHT_PANELS, filterWords, localViewIntent, runNamed, slashView, splitSlash, viewIntro, viewSpec, viewTab } from '../chatViews.js'
import { featureCatalog, searchFeatures } from '../featureCatalog.js'
import { seedFilters, buildPeople } from '../peopleExplorer.js'
import { RUN_CARD_TABS } from '../runCard.js'

const runs = [
  { name: 'fitloop_launch', title: 'FitLoop launch: should we price at $9?' },
  { name: 'kenya_pilot', title: 'Kenya pilot' }
]
const ask = (text, opts = {}) => localViewIntent(text, { runs, ...opts })

test('the view list matches the chat agent open_view enum and every run view has a card tab', () => {
  assert.deepEqual(Object.keys(CHAT_VIEWS).sort(), ['activity', 'audience', 'brain_response', 'buyer_responses', 'compare', 'connectors',
    'dashboard_map', 'insights', 'landing', 'people', 'projects', 'reports', 'results', 'settings_summary', 'skills', 'social_feed', 'spend', 'world_map'])
  assert.deepEqual(Object.keys(INSIGHT_PANELS), ['activity_calendar', 'intent', 'objections', 'audiences', 'trust', 'spend', 'live_runs'])
  const tabs = new Set(RUN_CARD_TABS.map((t) => t.id))
  for (const [view, info] of Object.entries(CHAT_VIEWS)) if (info.kind === 'run') assert.ok(tabs.has(viewTab(view)), view)
  // every run page tab is reachable as a view
  for (const tab of tabs) assert.ok(Object.entries(CHAT_VIEWS).some(([v, i]) => i.kind === 'run' && viewTab(v) === tab), tab)
})

test('owner examples are answered locally, with no model', () => {
  assert.deepEqual(ask('show the people in Kenya'), { view: 'people', run: 'fitloop_launch', filters: { country: 'Kenya' } })
  assert.deepEqual(ask('Show buyer responses that said no'), { view: 'buyer_responses', run: 'fitloop_launch', filters: { verdict: 'no' } })
  assert.deepEqual(ask('show the dashboard map'), { view: 'dashboard_map' })
  assert.deepEqual(ask("what's my spend?"), { view: 'spend' })
  assert.deepEqual(ask('Which connectors are on?'), { view: 'connectors' })
  assert.deepEqual(ask('open the landing analysis'), { view: 'landing', run: 'fitloop_launch' })
})

test('more free requests: filters, panels, settings and a named run', () => {
  assert.deepEqual(ask('who said no'), { view: 'buyer_responses', run: 'fitloop_launch', filters: { verdict: 'no' } })
  assert.deepEqual(ask('show responses about price'), { view: 'buyer_responses', run: 'fitloop_launch', filters: { objection: 'price' } })
  assert.deepEqual(ask('show the people who would buy'), { view: 'people', run: 'fitloop_launch', filters: { verdict: 'yes' } })
  assert.deepEqual(ask('show the people in the students segment'), { view: 'people', run: 'fitloop_launch', filters: { segment: 'Students' } })
  assert.deepEqual(ask('show the people in Kenya for kenya pilot'), { view: 'people', run: 'kenya_pilot', filters: { country: 'Kenya' } })
  assert.deepEqual(ask('Can you show the activity calendar?'), { view: 'insights', panel: 'activity_calendar' })
  assert.deepEqual(ask('show objections across all runs'), { view: 'insights', panel: 'objections' })
  assert.deepEqual(ask('show the dashboard'), { view: 'insights' })
  assert.deepEqual(ask('what is running now'), { view: 'insights', panel: 'live_runs' })
  assert.deepEqual(ask('how much have I spent so far'), { view: 'spend' })
  assert.deepEqual(ask('which model am I using'), { view: 'settings_summary' })
  assert.deepEqual(ask('show my projects'), { view: 'projects' })
  assert.deepEqual(ask('show skills'), { view: 'skills' })
  assert.deepEqual(ask('show me the brain response'), { view: 'brain_response', run: 'fitloop_launch' })
  assert.deepEqual(ask('show the activity'), { view: 'activity', run: 'fitloop_launch' })
})

test('"people in Kenya" stays a place even when a run title mentions Kenya', () => {
  assert.deepEqual(ask('show the people in Kenya').filters, { country: 'Kenya' })
  assert.equal(ask('show the people in Kenya').run, 'fitloop_launch')
})

test('the selected run wins over the newest, and no run says so', () => {
  assert.equal(ask('show the people', { run: 'kenya_pilot' }).run, 'kenya_pilot')
  assert.deepEqual(localViewIntent('show the people', { runs: [] }), { view: 'people', needsRun: true })
  // workspace views need no run
  assert.deepEqual(localViewIntent("what's my spend", { runs: [] }), { view: 'spend' })
})

test('ordinary questions and paid requests still go to the chat agent', () => {
  for (const text of ['Why did people say no?', 'Which audience should we target?', 'show my saved runs and reports', 'Compare my last two experiments',
    'show the people who like dogs', 'Test a cheaper price and show me the cost before anything runs', 'Run a focus group about pricing',
    'What should my spend be for a launch?', 'show me a plan for the people in Kenya', 'Ask the buyers in Kenya what they would pay', '']) {
    assert.equal(ask(text), null, text)
  }
})

test('view specs keep only what a view takes', () => {
  assert.deepEqual(viewSpec({ view: 'people', run: 'x', filters: { country: 'Kenya', objection: 'price', verdict: 'NO' } }), { view: 'people', run: 'x', filters: { country: 'Kenya', verdict: 'no' } })
  assert.deepEqual(viewSpec({ view: 'spend', run: 'x', panel: 'intent' }), { view: 'spend' })
  assert.deepEqual(viewSpec({ view: 'insights', panel: 'nope' }), { view: 'insights' })
  assert.deepEqual(viewSpec({ view: 'buyer_responses', run: 'x', filters: { verdict: 'perhaps', objection: 'Price' } }), { view: 'buyer_responses', run: 'x', filters: { objection: 'price' } })
  assert.equal(viewSpec({ view: 'nonsense' }), null)
})

test('intros say it was free and mark simulated numbers', () => {
  assert.match(viewIntro({ view: 'people', filters: { country: 'Kenya' } }, 'FitLoop'), /in Kenya.*no model call.*simulated/s)
  assert.match(viewIntro({ view: 'spend' }), /estimate.*not a bill/)
  assert.match(viewIntro({ view: 'buyer_responses', filters: { verdict: 'no' } }, 'FitLoop'), /who said no/)
  assert.equal(filterWords({ verdict: 'yes', segment: 'Students' }), 'in the Students segment, who would buy')
  for (const view of Object.keys(CHAT_VIEWS)) assert.ok(viewIntro({ view }), view)
})

test('runs are found by title or folder name', () => {
  assert.equal(runNamed('kenya pilot', runs), 'kenya_pilot')
  assert.equal(runNamed('the fitloop launch run', runs), 'fitloop_launch')
  assert.equal(runNamed('kenya', runs, { exact: true }), '')
  assert.equal(runNamed('ab', runs), '')
})

test('slash commands: the required list, each with a label, a description and a free or asks-first badge', () => {
  const required = ['/people', '/responses', '/activity', '/map', '/dashboard', '/compare', '/landing', '/brain', '/connectors', '/settings', '/spend', '/new-experiment', '/focus-group', '/ask']
  for (const command of required) {
    const item = featureCatalog.find((f) => f.command === command)
    assert.ok(item, command)
    assert.ok(item.label && item.description, command)
    assert.ok(['free', 'approval'].includes(item.cost), command)
  }
  const cost = (c) => featureCatalog.find((f) => f.command === c).cost
  for (const c of ['/people', '/responses', '/activity', '/map', '/dashboard', '/compare', '/landing', '/brain', '/connectors', '/settings', '/spend']) assert.equal(cost(c), 'free', c)
  for (const c of ['/new-experiment', '/focus-group', '/ask']) assert.equal(cost(c), 'approval', c)
  // every catalog entry has a badge, and commands are unique
  assert.ok(featureCatalog.every((f) => ['free', 'approval'].includes(f.cost)))
  assert.equal(new Set(featureCatalog.map((f) => f.command)).size, featureCatalog.length)
  // views are free and say which view they open
  for (const f of featureCatalog.filter((x) => x.view)) { assert.equal(f.cost, 'free'); assert.ok(CHAT_VIEWS[f.view], f.id) }
  // the menu finds them by typing
  assert.equal(searchFeatures('/peop')[0].command, '/people')
  assert.equal(searchFeatures('/spend')[0].command, '/spend')
  assert.equal(searchFeatures('/new-experiment')[0].action, 'experiment')
})

test('slash commands take words after them', () => {
  assert.deepEqual(splitSlash('/people Kenya'), { command: '/people', rest: 'Kenya' })
  assert.deepEqual(splitSlash('/spend'), { command: '/spend', rest: '' })
  assert.equal(splitSlash('people'), null)
  assert.deepEqual(slashView('people', 'kenya', { runs }), { view: 'people', run: 'fitloop_launch', filters: { country: 'Kenya' } })
  assert.deepEqual(slashView('people', 'no', { runs }), { view: 'people', run: 'fitloop_launch', filters: { verdict: 'no' } })
  assert.deepEqual(slashView('buyer_responses', 'price', { runs }), { view: 'buyer_responses', run: 'fitloop_launch', filters: { objection: 'price' } })
  assert.deepEqual(slashView('people', 'for kenya pilot', { runs }), { view: 'people', run: 'kenya_pilot' })
  assert.deepEqual(slashView('insights', 'objections', { runs }), { view: 'insights', panel: 'objections' })
  assert.deepEqual(slashView('insights', 'calendar', { runs }), { view: 'insights', panel: 'activity_calendar' })
  assert.deepEqual(slashView('people', '', { runs: [] }), { view: 'people', needsRun: true })
  assert.deepEqual(slashView('spend', '', { runs: [] }), { view: 'spend' })
})

test('people filters from the chat match the run values, or become a search', () => {
  const rows = buildPeople({ index: [
    { agent_id: 1, name: 'Amina', country: 'Kenya', segment: 'Students' },
    { agent_id: 2, name: 'Ravi', country: 'India', segment: 'Parents' }
  ] })
  assert.deepEqual(seedFilters(rows, { country: 'kenya' }).country, ['Kenya'])
  assert.deepEqual(seedFilters(rows, { country: 'students' }).segment, ['Students'])      // a segment asked for as a place
  assert.deepEqual(seedFilters(rows, { segment: 'India' }).country, ['India'])
  assert.equal(seedFilters(rows, { country: 'Peru' }).query, 'Peru')                      // never silently dropped
  assert.deepEqual(seedFilters(rows, { verdict: 'NO' }).verdict, ['no'])
})
