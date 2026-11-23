import test from 'node:test'
import assert from 'node:assert/strict'
import {
  compareGapNote, compareSections, compareVerdict, continueEntries, decisionText, displayTitle, evidenceTitle,
  findEvidenceChat, isCompareRequest, mentionedRuns, pickCompareRuns, shareText
} from '../compareRuns.js'

// newest first, as the run index returns them
const runs = [
  { name: 'fitloop_launch', title: 'FitLoop launch: does a free week convert?' },
  { name: 'fitloop', title: 'FitLoop (first test)' },
  { name: 'csca', title: 'CSCA prep course' },
  { name: 'fast150', title: 'Fast 150' }
]

test('short display title cuts at a colon or bracket', () => {
  assert.equal(displayTitle('FitLoop launch: does a free week convert?'), 'FitLoop launch')
  assert.equal(displayTitle('FitLoop (first test)'), 'FitLoop')
  assert.equal(displayTitle('Plain title'), 'Plain title')
  assert.equal(displayTitle(': odd'), ': odd')
})

test('decision reads in sentence case', () => {
  assert.equal(decisionText('ITERATE'), 'Iterate')
  assert.equal(decisionText('no_go'), 'No go')
})

test('compare requests are recognised, other messages are not', () => {
  assert.ok(isCompareRequest('compare my last two experiments', runs))
  assert.ok(isCompareRequest('Compare fitloop_launch and fitloop', runs))
  assert.ok(isCompareRequest('fitloop_launch vs csca', runs))
  assert.ok(!isCompareRequest('compare our price with Peloton', runs))
  assert.ok(!isCompareRequest('what did people say about the price?', runs))
  assert.ok(!isCompareRequest('fitloop vs gyms', runs))
})

test('a folder name inside a longer one is not matched twice', () => {
  assert.deepEqual(mentionedRuns('compare fitloop_launch and fitloop', runs), ['fitloop_launch', 'fitloop'])
  assert.deepEqual(mentionedRuns('compare fitloop and fitloop_launch', runs), ['fitloop', 'fitloop_launch'])
  assert.deepEqual(mentionedRuns('compare fitloop_launch with itself', runs), ['fitloop_launch'])
})

test('titles and short titles match as well as folder names', () => {
  assert.deepEqual(mentionedRuns('Compare the CSCA prep course with Fast 150', runs), ['csca', 'fast150'])
})

test('runs are picked from the text, then the selected run, then the newest', () => {
  assert.deepEqual(pickCompareRuns('compare csca and fast150', runs, 'fitloop'), { a: 'csca', b: 'fast150' })
  assert.deepEqual(pickCompareRuns('compare csca with something', runs, 'fitloop'), { a: 'csca', b: 'fitloop' })
  assert.deepEqual(pickCompareRuns('compare my last two experiments', runs, ''), { a: 'fitloop_launch', b: 'fitloop' })
  assert.deepEqual(pickCompareRuns('compare my last two experiments', runs, 'csca'), { a: 'csca', b: 'fitloop_launch' })
  assert.deepEqual(pickCompareRuns('compare', runs.slice(0, 1), ''), { a: 'fitloop_launch', b: '' })
  assert.deepEqual(pickCompareRuns('compare', runs, 'missing'), { a: 'fitloop_launch', b: 'fitloop' })
})

test('evidence links reuse the chat with the same run and request', () => {
  const chats = [
    { id: 'c3', run: 'fitloop', messages: [{ role: 'user', content: 'Show all reports', evidenceRun: 'fitloop' }] },
    { id: 'c2', run: 'fitloop_launch', messages: [{ role: 'user', content: 'Show the social feed', evidenceRun: 'fitloop_launch' }] },
    { id: 'c1', run: 'fitloop_launch', messages: [{ role: 'user', content: 'Show all reports', evidenceRun: 'fitloop_launch' }] },
    { id: 'c0', run: 'fitloop_launch', messages: [{ role: 'user', content: 'Show all reports' }] }
  ]
  assert.equal(findEvidenceChat(chats, 'fitloop_launch', 'Show all reports')?.id, 'c1')
  assert.equal(findEvidenceChat(chats, 'fitloop_launch', 'Show the social feed')?.id, 'c2')
  assert.equal(findEvidenceChat(chats, 'csca', 'Show all reports'), null)
  assert.equal(evidenceTitle('Social feed', runs[0].title), 'Social feed · FitLoop launch')
})

test('Continue cards keep one chat per title and run, and a slot for the newest run without a chat', () => {
  const msg = [{ role: 'user', content: 'hi' }]
  const chats = [
    { id: 'a', title: 'Reports · FitLoop launch', run: 'fitloop_launch', messages: msg },
    { id: 'b', title: 'Reports · FitLoop launch', run: 'fitloop_launch', messages: msg },
    { id: 'c', title: 'Pricing ideas', run: '', messages: msg },
    { id: 'd', title: 'Audience · FitLoop', run: 'fitloop', messages: msg },
    { id: 'e', title: 'Empty', run: 'csca', messages: [] }
  ]
  const items = continueEntries(chats, runs, 3)
  assert.deepEqual(items.map((x) => x.kind === 'chat' ? x.chat.id : x.run.name), ['a', 'c', 'csca'])

  // no runs without a chat: every slot can hold a chat
  const all = continueEntries(chats, runs.slice(0, 2), 3)
  assert.deepEqual(all.map((x) => x.chat.id), ['a', 'c', 'd'])

  // few chats: runs fill the row, newest first
  const few = continueEntries([], runs, 3)
  assert.deepEqual(few.map((x) => x.run.name), ['fitloop_launch', 'fitloop', 'csca'])
})

test('shares under 100 people read as x of n', () => {
  assert.equal(shareText(3.6, 28), '1 of 28 (4%)')
  assert.equal(shareText(53.6, 28, 15), '15 of 28 (54%)')
  assert.equal(shareText(12.34, 400), '12.3%')
  assert.equal(shareText(null, 28), null)
})

const run = (name, convertYes, n, extra = {}) => ({
  name, title: `${name} title: detail`, decision: 'iterate', decisionSummary: 'Fix and retest.', count: n,
  mk: { answered: n, overall: { n, convert_yes: convertYes, convert_maybe: 50, convert_no: 50 - convertYes, click_yes: 10, interest: 4.8, trust: 3.7 },
    by_segment: [{ key: 'Parents', n: 10, convert_yes: 20 }, { key: 'Students', n: 8, convert_yes: 0 }],
    objections: [{ label: 'Trust', count: 5, share: 25 }] },
  ...extra
})
const wouldBuy = (sections) => sections.find((s) => s.title === 'Buying intent').rows.find((r) => r.label === 'Would buy')

test('the higher badge on would buy needs a 5-point gap and 30 answers in the smaller run', () => {
  assert.equal(wouldBuy(compareSections(run('a', 10, 40), run('b', 13, 40))).lead, null)
  assert.match(compareGapNote(run('a', 10, 40), run('b', 13, 40)), /too close to call/)
  assert.equal(wouldBuy(compareSections(run('a', 10, 20), run('b', 30, 200))).lead, null)
  assert.match(compareGapNote(run('a', 10, 20), run('b', 30, 200)), /too close to call/)
  assert.equal(wouldBuy(compareSections(run('a', 10, 40), run('b', 20, 40))).lead, 1)
  assert.doesNotMatch(compareGapNote(run('a', 10, 40), run('b', 20, 40)), /too close/)
  assert.match(compareVerdict(run('a', 10, 40), run('b', 20, 40)), /^b title leans ahead/)
  assert.match(compareVerdict(run('a', 10, 40), run('b', 12, 40)), /Neither run is clearly ahead/)
  assert.match(compareVerdict(run('a', 10, 40), { name: 'b', title: 'B', decision: 'go' }), /^Only a title has a buyer survey/)
})

test('compare lists every section with labelled rows', () => {
  const feed = { summary: { per_creative: { x: { expected_ctr: 2.1 }, y: { expected_ctr: 5.9 } } }, creatives: [{ id: 'x', name: 'Ad X' }, { id: 'y', name: 'Ad Y' }] }
  const pitch = { pitch_score: 39, verdict_after: { yes: 7.1 }, people_pitched: 28, hot_leads: [1, 2, 3] }
  const story = { platforms: { reddit: { total_posts: 5, comments: 27, likes: 19 }, twitter: { total_posts: 29, comments: 0, likes: 22 } } }
  const sections = compareSections(run('a', 4, 28, { feed, pitch, story }), run('b', 20, 28))
  assert.deepEqual(sections.map((s) => s.title), ['At a glance', 'Buying intent', 'Audiences', 'Why people said no', 'Ads in the feed', 'Sales pitch', 'Social activity'])
  const get = (title, label) => sections.find((s) => s.title === title).rows.find((r) => r.label === label).values
  assert.deepEqual(get('At a glance', 'Decision')[0], { pill: 'Iterate', tone: 'iterate' })
  assert.equal(get('At a glance', 'Answered the survey')[0], '28 of 28 (100%)')
  assert.equal(get('Buying intent', 'Interest')[0], '4.8 / 10')
  assert.equal(get('Audiences', 'Strongest')[0], 'Parents: 2 of 10 (20%) would buy')
  assert.equal(get('Audiences', 'Weakest')[0], 'Students: 0 of 8 (0%) would buy')
  assert.equal(get('Why people said no', 'Main reason')[0], 'Trust: 5 of 28 (25%)')
  assert.equal(get('Ads in the feed', 'Best ad (expected click-through)')[0], 'Ad Y: 5.9%')
  assert.deepEqual(get('Ads in the feed', 'Every ad, ranked')[0], { list: ['Ad Y: 5.9%', 'Ad X: 2.1%'] })
  assert.equal(get('Sales pitch', 'Said yes after the pitch')[0], '2 of 28 (7%)')
  assert.equal(get('Sales pitch', 'Hot leads')[0], '3')
  assert.equal(get('Social activity', 'Posts')[0], '34 (Reddit 5 · Twitter 29)')
  assert.equal(get('Social activity', 'Likes')[1], null)
})
