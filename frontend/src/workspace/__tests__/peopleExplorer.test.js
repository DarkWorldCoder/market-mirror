import test from 'node:test'
import assert from 'node:assert/strict'
import {
  AGE_BANDS, MAX_COMPARE, activeFilterCount, activityText, ageBand, buildPeople, compareRows, csvCell, csvFileName, decisionCard,
  emptyFilters, facetOptions, filterPeople, initials, listText, peopleCsv, peopleSummary, segmentColorMap, sortPeople, stripContacts,
  toggleCompare, toggleValue, verdictKey
} from '../peopleExplorer.js'

// shapes copied from real saved runs (fitloop_1000_sonnet): ids are strings in persona_index, numbers in agent_stats
const index = [
  { agent_id: '9', kind: 'persona', name: 'Yasmin Desai', age: '32', gender: 'female', city: 'Pune', country: 'India', segment: 'India young professionals', occupation: 'Marketing coordinator', income_level: 'high', education: 'vocational or diploma', media_diet: 'Instagram and creators', phone: 'iPhone 12, 3 years old', data_plan: 'Airtel postpaid', interview_summary: "I'm Yasmin, 32, living in Pune with my boyfriend. I grew up in Gujarat.", weight: 1.0, bde: null },
  { agent_id: '12', name: 'Juan Dela Cruz', age: 47, gender: 'male', city: 'Cebu', country: 'Philippines', segment: 'Philippines parents', occupation: 'BPO customer service representative', bde: { decision_procedure: { speed: 'considered', risk: 'neutral', stoppers: ['hidden auto-renewal'], who_they_ask: 'Colleagues' }, evaluation: { dealbreakers: ['hidden auto-renewal', 'no cancel reminder'], monthly_discretionary: '₱3,000' }, background: { says_vs_does: 'Says he needs evidence, yet buys on a good Reel.' } } },
  { agent_id: '15', name: 'Amina Otieno', age: '22', gender: 'female', city: 'Nairobi', country: 'Kenya', segment: 'Students', occupation: 'bpo customer service representative' },
  { agent_id: '20', name: 'Brian Mwangi', age: '', gender: 'male', city: 'Mombasa', country: 'Kenya', segment: 'Students', occupation: 'Student' },
  { agent_id: '3', kind: 'community', name: 'Bengaluru Fitness Buddies' },
  { agent_id: '1', kind: 'graph', name: 'Fitloop' }
]
const survey = {
  responses: [
    { agent_id: '9', name: 'Yasmin Desai', answer: { would_convert: 'maybe', objection_type: 'trust', main_objection: 'Scared of being charged after the trial', would_change_mind: 'No card, cancel in 2 taps', quote: 'Pehle koi real review dikhao' } },
    { agent_id: '12', answer: { would_convert: 'no', objection_type: 'price', main_objection: 'Too expensive for my family', quote: '' } },
    { agent_id: '15', answer: { would_convert: 'yes', objection_type: 'trust', main_objection: 'Unsure about privacy', quote: 'I would try it tonight' } },
    { agent_id: '20', answer: null }
  ]
}
const stats = [
  { agent_id: 9, total_actions: 4, action_types: { CREATE_POST: 1, LIKE_POST: 3 }, reddit_actions: 4 },
  { agent_id: 15, total_actions: 9, action_types: { DO_NOTHING: 9 } }
]
const thoughts = [
  { agent_id: 12, source: 'ad in feed', text: 'Another subscription, no thanks.' },
  { agent_id: 12, source: 'survey', text: 'Too expensive for my family' }
]
const colors = ['#111111', '#222222', '#333333']
const rows = buildPeople({ index, survey, stats, thoughts, colors })
const byId = Object.fromEntries(rows.map((r) => [r.id, r]))

test('buildPeople keeps only simulated people and joins answers, activity and thoughts by id', () => {
  assert.deepEqual(rows.map((r) => r.id), ['9', '12', '15', '20'])
  assert.equal(byId['9'].verdict, 'maybe')
  assert.equal(byId['9'].actions, 4)
  assert.equal(byId['9'].why, 'Pehle koi real review dikhao')
  assert.equal(byId['9'].whySource, 'In their words')
  assert.equal(byId['12'].why, 'Too expensive for my family')
  assert.equal(byId['12'].thought, 'Another subscription, no thanks.')
  assert.equal(byId['20'].asked, false)
  assert.equal(byId['20'].verdict, 'none')
  assert.equal(byId['20'].age, null)
  assert.equal(byId['20'].ageBand, 'Age not saved')
  assert.equal(byId['12'].bde.evaluation.monthly_discretionary, '₱3,000')
})

test('segment colours follow first appearance, matching the audience card', () => {
  assert.deepEqual(segmentColorMap(index, colors), { 'India young professionals': '#111111', 'Philippines parents': '#222222', Students: '#333333' })
  assert.equal(byId['15'].color, '#333333')
})

test('small value helpers', () => {
  assert.equal(initials('Yasmin Desai'), 'YD')
  assert.equal(initials(''), '?')
  assert.equal(listText("['English', 'Hindi']"), 'English, Hindi')
  assert.equal(verdictKey('YES'), 'yes')
  assert.equal(verdictKey(undefined), 'none')
  assert.equal(ageBand(24), AGE_BANDS[0])
  assert.equal(ageBand('25'), '25 to 34')
  assert.equal(ageBand(60), '55 and over')
})

test('facet options count every person and keep a fixed order for verdicts and ages', () => {
  const f = facetOptions(rows)
  assert.deepEqual(f.verdict.map((o) => o.value), ['yes', 'maybe', 'no', 'none'])
  assert.equal(f.verdict.find((o) => o.value === 'none').label, 'Not asked')
  assert.deepEqual(f.country[0], { value: 'Kenya', label: 'Kenya', count: 2 })
  assert.deepEqual(f.ageBand.map((o) => o.value), ['Under 25', '25 to 34', '45 to 54', 'Age not saved'])
})

test('filters: any value within a group, every group, every search word', () => {
  assert.deepEqual(filterPeople(rows, { ...emptyFilters(), country: ['Kenya', 'India'] }).map((r) => r.id), ['9', '15', '20'])
  assert.deepEqual(filterPeople(rows, { ...emptyFilters(), country: ['Kenya'], verdict: ['none'] }).map((r) => r.id), ['20'])
  assert.deepEqual(filterPeople(rows, { query: 'pune' }).map((r) => r.id), ['9'])
  assert.deepEqual(filterPeople(rows, { query: 'expensive family' }).map((r) => r.id), ['12'])
  assert.deepEqual(filterPeople(rows, { query: 'bpo' }).map((r) => r.id), ['12', '15'])
  assert.deepEqual(filterPeople(rows, { query: 'subscription' }).map((r) => r.id), ['12'], 'words they wrote in the feed are searchable')
  assert.equal(filterPeople(rows, { query: 'nobody-here' }).length, 0)
  assert.equal(activeFilterCount({ ...emptyFilters(), query: ' x ', gender: ['Male'] }), 2)
  assert.deepEqual(toggleValue(['a'], 'a'), [])
  assert.deepEqual(toggleValue(['a'], 'b'), ['a', 'b'])
})

test('sorting by name, age, activity and answer', () => {
  assert.deepEqual(sortPeople(rows, 'name').map((r) => r.id), ['15', '20', '12', '9'])
  assert.deepEqual(sortPeople(rows, 'age').map((r) => r.id), ['15', '9', '12', '20'], 'missing ages go last')
  assert.deepEqual(sortPeople(rows, 'active').map((r) => r.id), ['9', '15', '20', '12'], 'rounds spent doing nothing do not count as activity')
  assert.equal(byId['15'].actions, 0)
  assert.equal(byId['9'].actions, 4)
  assert.deepEqual(sortPeople(rows, 'answer').map((r) => r.id), ['15', '9', '12', '20'])
  assert.deepEqual(rows.map((r) => r.id), ['9', '12', '15', '20'], 'the input is not reordered')
})

test('summary counts only people who were asked for the would-buy share', () => {
  const s = peopleSummary(rows)
  assert.equal(s.people, 4)
  assert.equal(s.asked, 3)
  assert.equal(s.yes, 1)
  assert.equal(s.buyText, '1 of 3 asked (33.3%)')
  assert.equal(s.topObjection.label, 'Trust')
  assert.equal(s.topObjection.count, 2)
  assert.equal(s.topObjection.example, 'Scared of being charged after the trial')
  assert.deepEqual(s.topOccupations[0], { label: 'BPO customer service representative', count: 2 }, 'job titles are grouped ignoring case')
  const none = peopleSummary([byId['20']])
  assert.equal(none.buyText, 'Nobody here was asked')
  assert.equal(none.topObjection, null)
})

test('compare keeps at most three and a second tick removes', () => {
  let ids = []
  for (const id of ['9', '12', '15', '20']) ids = toggleCompare(ids, id)
  assert.equal(MAX_COMPARE, 3)
  assert.deepEqual(ids, ['9', '12', '15'])
  assert.deepEqual(toggleCompare(ids, 12), ['9', '15'])
})

test('compare rows show profile, answer, objection, activity and a quote, dropping empty fields', () => {
  const table = compareRows([byId['9'], byId['12']])
  const get = (label) => table.find((r) => r.label === label)?.values
  assert.deepEqual(get('Would buy (simulated)'), ['Maybe', 'Would not buy'])
  assert.deepEqual(get('Main objection'), ['Trust: Scared of being charged after the trial', 'Price: Too expensive for my family'])
  assert.deepEqual(get('What they did'), ['Wrote 1 post and liked 3 posts', 'No social activity recorded'])
  assert.deepEqual(get('A quote'), ['Pehle koi real review dikhao', 'Another subscription, no thanks.'])
  assert.deepEqual(get('How they decide'), ['', 'Considered, neutral on risk'])
  assert.equal(table.some((r) => r.label === 'Phone'), false)
})

test('decision card lines and activity sentences', () => {
  const card = decisionCard(byId['12'].bde)
  assert.deepEqual(card.find((c) => c.label === 'What stops them').value, 'hidden auto-renewal, no cancel reminder')
  assert.equal(card.find((c) => c.label === 'Spare money a month').value, '₱3,000')
  assert.deepEqual(decisionCard(null), [])
  assert.equal(activityText({ total_actions: 9, action_types: { DO_NOTHING: 9 } }), '9 recorded actions, none of them posts or likes')
})

test('CSV has a header, one row per person, no contact details, and safe cells', () => {
  const csv = peopleCsv(rows)
  const lines = csv.trim().split('\r\n')
  assert.equal(lines.length, 5)
  assert.ok(lines[0].startsWith('agent_id,name,age,gender,city,country,segment'))
  assert.ok(lines[0].endsWith(',simulated'))
  assert.ok(!/phone|data_plan|email/.test(lines[0]))
  assert.ok(!csv.includes('iPhone') && !csv.includes('Airtel'))
  assert.ok(lines[4].includes(',not asked,'))
  assert.equal(csvCell('a, "b"'), '"a, ""b"""')
  assert.equal(csvCell('=HYPERLINK("x")'), `"'=HYPERLINK(""x"")"`)
  assert.equal(csvCell('-3'), '-3')
  assert.equal(stripContacts('mail me at a.b@example.com or +91 98765 43210'), 'mail me at [email removed] or [number removed]')
  assert.equal(stripContacts('₹8,000 a month'), '₹8,000 a month')
  assert.equal(csvFileName('fitloop 1000/x', true), 'fitloop_1000_x_people_filtered_simulated.csv')
})
