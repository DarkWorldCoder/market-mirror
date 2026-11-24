import test from 'node:test'
import assert from 'node:assert/strict'
import {
  EVIDENCE_PROMPTS, RUN_CARD_TABS, actionMix, evidencePrompt, localRunIntent, messageRun, objectionAnswer, segmentAnswer, shownChips, activityRounds, buyerResponses, compareChoices, hasFeed, moveTab, nextStepChips, reportDownloadFile,
  resultsFile, runCardIntro, runCardStats, tabForView, topActors, verdictCounts
} from '../runCard.js'

const runs = [
  { name: 'fitloop_1000_sonnet', title: 'Fitloop, 1,000 simulated customers (Sonnet)', decision: 'iterate' },
  { name: 'fitloop', title: 'FitLoop (first test)', decision: 'go' },
  { name: 'csca', title: 'CSCA prep course' }
]
const summary = {
  decision: { decision: 'iterate', summary: 'Promising, but fix the blockers.' },
  marketing: {
    people: 1008, offer: 'Free week', pricing: { by_segment: [] },
    overall: { n: 1001, convert_yes: 1.1, convert_maybe: 74.8 },
    by_segment: [{ key: 'Students', n: 214 }, { key: 'India parents', n: 142 }],
    objections: [{ label: 'Trust', share: 40 }]
  }
}

test('card tabs match the run page tabs and their order', () => {
  assert.deepEqual(RUN_CARD_TABS.map((t) => t.id), ['results', 'market', 'people', 'thinking', 'activity', 'feed'])
  assert.deepEqual(RUN_CARD_TABS.map((t) => t.label), ['Results', 'Audience & world', 'People', 'Buyer responses', 'Activity', 'Social feed'])
})

test('views from links, the agent and evidence labels map to card tabs', () => {
  assert.equal(tabForView('reports'), 'results')
  assert.equal(tabForView('world_map'), 'market')
  assert.equal(tabForView('Audience'), 'market')
  assert.equal(tabForView('social_feed'), 'feed')
  assert.equal(tabForView('people'), 'people')
  assert.equal(tabForView('Personas'), 'people')
  assert.equal(tabForView('Social feed'), 'feed')
  assert.equal(tabForView('Thinking'), 'thinking')
  assert.equal(tabForView('activity'), 'activity')
  assert.equal(tabForView('Buyer responses'), 'thinking')
  assert.equal(tabForView(''), 'results')
  assert.equal(tabForView('nonsense'), 'results')
})

test('arrow keys wrap, Home and End jump, other keys do nothing', () => {
  assert.equal(moveTab(RUN_CARD_TABS, 'results', 'ArrowRight'), 'market')
  assert.equal(moveTab(RUN_CARD_TABS, 'results', 'ArrowLeft'), 'feed')
  assert.equal(moveTab(RUN_CARD_TABS, 'feed', 'ArrowRight'), 'results')
  assert.equal(moveTab(RUN_CARD_TABS, 'activity', 'Home'), 'results')
  assert.equal(moveTab(RUN_CARD_TABS, 'market', 'End'), 'feed')
  assert.equal(moveTab(RUN_CARD_TABS, 'market', 'Enter'), null)
  assert.equal(moveTab([], 'market', 'ArrowRight'), null)
})

test('header numbers are labelled and small samples read as counts', () => {
  const big = runCardStats({ title: 'Fitloop', people: 1008, summary })
  assert.equal(big.decisionLabel, 'Iterate')
  assert.equal(big.tone, 'iterate')
  assert.equal(big.summary, 'Promising, but fix the blockers.')
  assert.deepEqual(big.numbers.map((n) => [n.value, n.label]), [['1,008', 'people'], ['2', 'segments'], ['1.1%', 'would buy'], ['74.8%', 'maybe']])
  const small = runCardStats({ people: 28, summary: { marketing: { overall: { n: 28, convert_yes: 10.7 } } } })
  assert.deepEqual(small.numbers.find((n) => n.key === 'convert_yes'), { key: 'convert_yes', value: '3 of 28', label: 'would buy', note: '10.7%' })
  assert.deepEqual(runCardStats(null).numbers, [])
  assert.equal(runCardStats({ summary: {} }).decisionLabel, '')
})

test('download and results files prefer the plain-language report', () => {
  assert.equal(reportDownloadFile(['summary.json', 'report.md', 'market_report.md']), 'market_report.md')
  assert.equal(reportDownloadFile(['summary.json']), 'summary.json')
  assert.equal(reportDownloadFile([]), '')
  assert.equal(resultsFile(['market_report.json', 'summary.json']), 'summary.json')
  assert.equal(resultsFile(['report.md']), '')
  assert.ok(hasFeed(['posts_reddit.json']))
  assert.ok(!hasFeed(['summary.json']))
})

test('buyer responses keep the person, verdict and words, and filter by verdict', () => {
  const survey = { responses: [
    { agent_id: 1, name: 'Ana', answer: { would_convert: 'yes', quote: 'I would try it', main_objection: '' } },
    { agent_id: 2, name: 'Ben', answer: { would_convert: 'No', main_objection: 'Too pricey', would_change_mind: 'A discount' } },
    { agent_id: 3, answer: { would_convert: 'maybe' } },
    null
  ] }
  const rows = buyerResponses(survey)
  assert.equal(rows.length, 2)
  assert.deepEqual(rows[1], { id: '2', who: 'Ben', verdict: 'no', said: '', objection: 'Too pricey', change: 'A discount' })
  assert.deepEqual(buyerResponses(survey, 'yes').map((r) => r.who), ['Ana'])
  assert.deepEqual(verdictCounts(survey), { yes: 1, maybe: 1, no: 1 })
  assert.deepEqual(buyerResponses(null), [])
})

test('activity rounds are ordered with bar shares, actors leave out doing nothing', () => {
  const rounds = activityRounds([{ round_num: 2, total_actions: 50, active_agents_count: 9 }, { round_num: 1, total_actions: 100 }, { round_num: 'x', total_actions: 3 }])
  assert.deepEqual(rounds.map((r) => [r.round, r.share]), [[1, 100], [2, 50]])
  assert.equal(rounds[1].active, 9)
  const actors = topActors([
    { agent_id: 1, agent_name: 'Ana', action_types: { DO_NOTHING: 9, CREATE_COMMENT: 2, LIKE_POST: 1 } },
    { agent_id: 2, agent_name: 'Ben', action_types: { DO_NOTHING: 5 } },
    { agent_id: 3, agent_name: 'Cy', action_types: { CREATE_POST: 4 } }
  ])
  assert.deepEqual(actors.map((a) => [a.who, a.acted]), [['Cy', 4], ['Ana', 3]])
  assert.equal(actors[1].detail, '2 comments, 1 post likes')
  assert.deepEqual(actionMix([{ action_types: { DO_NOTHING: 4, LIKE_POST: 2 } }, { action_types: { LIKE_POST: 1, CREATE_POST: 1 } }]).map((r) => [r.label, r.count]), [['post likes', 3], ['posts', 1]])
})

test('compare choices leave out the current run', () => {
  assert.deepEqual(compareChoices(runs, 'fitloop').map((r) => r.name), ['fitloop_1000_sonnet', 'csca'])
  assert.equal(compareChoices(runs, 'fitloop', 1)[0].title, 'Fitloop, 1,000 simulated customers')
})

test('next-step chips: free ones answer from saved files, paid ones go through the agent for approval', () => {
  const chips = nextStepChips({ run: 'fitloop_1000_sonnet', title: runs[0].title, runs, files: ['config.json', 'summary.json', 'feed_story.json'], summary })
  assert.equal(chips.length, 4)
  assert.deepEqual(chips.map((c) => c.label), ['Why did people say no?', 'Show the world map', 'Compare with the last run', 'Test a cheaper price'])
  const compare = chips.find((c) => c.kind === 'compare')
  assert.equal(compare.other, 'fitloop')
  assert.equal(compare.cost, 'free')
  const paid = chips.filter((c) => c.cost !== 'free')
  assert.ok(paid.length >= 1)
  for (const c of paid) {
    assert.equal(c.kind, 'agent')
    assert.equal(c.cost, 'approval')
    assert.match(c.prompt, /cost before anything runs/)
  }
  for (const c of chips.filter((x) => x.cost === 'free')) assert.notEqual(c.kind, 'agent')
  assert.equal(chips[0].query, 'objections')
})

test('chips adapt to what the run has', () => {
  const bare = nextStepChips({ run: 'csca', runs: [runs[2]], files: [], summary: {} })
  assert.deepEqual(bare.map((c) => c.id), ['follow-up'])
  assert.deepEqual(nextStepChips({}), [])
})

test('the run card intro names the view and says the numbers are simulated', () => {
  assert.match(runCardIntro('feed', 'FitLoop: a test'), /the social feed for \*\*FitLoop\*\*/)
  assert.match(runCardIntro('unknown', 'X'), /simulated buyers/)
})

test('chips leave out what the message already shows', () => {
  const chips = nextStepChips({ run: 'fitloop_1000_sonnet', title: runs[0].title, runs, files: ['config.json', 'feed_story.json'], summary, exclude: ['why-no', 'map'] })
  assert.ok(!chips.some((c) => c.id === 'why-no' || c.id === 'map'))
  assert.deepEqual(shownChips({ run_card: { run: 'x', tab: 'market' } }), ['map'])
  assert.deepEqual(shownChips({ run_card: { run: 'x', tab: 'thinking', verdict: 'no' } }), ['why-no'])
  assert.deepEqual(shownChips({ run_card: { run: 'x', tab: 'market', focus: 'segments' } }), ['map', 'segments'])
  assert.deepEqual(shownChips(null), [])
})

test('evidence prompts follow the card tabs', () => {
  assert.deepEqual(Object.keys(EVIDENCE_PROMPTS), RUN_CARD_TABS.map((t) => t.id))
  assert.equal(evidencePrompt('audience'), 'Show the audience and world map')
  assert.equal(evidencePrompt('reports'), 'Show the results')
})

test('only near-exact phrases are answered from the saved run', () => {
  assert.deepEqual(localRunIntent('Why did people say no?'), { kind: 'objections', tab: 'thinking', verdict: 'no' })
  assert.deepEqual(localRunIntent('Which audience should we target?'), { kind: 'segments', tab: 'market' })
  assert.deepEqual(localRunIntent('Show the world map'), { kind: 'view', tab: 'market' })
  assert.deepEqual(localRunIntent('show the social feed'), { kind: 'view', tab: 'feed' })
  assert.deepEqual(localRunIntent('Show the people'), { kind: 'view', tab: 'people' })
  assert.deepEqual(localRunIntent('Show all reports'), { kind: 'view', tab: 'results' })
  assert.deepEqual(localRunIntent('Show the 3D world and audience'), { kind: 'view', tab: 'market' })
  for (const p of Object.values(EVIDENCE_PROMPTS)) assert.equal(localRunIntent(p)?.kind, 'view')
  assert.equal(localRunIntent('Why did people say no to the second ad in India?'), null)
  assert.equal(localRunIntent('Show the social feed for my other run and summarize it'), null)
  assert.equal(localRunIntent(''), null)
})

test('objection and audience answers come from summary.json and stay labelled simulated', () => {
  const real = { marketing: { objections: [{ label: 'Trust / looks like a scam', share: 70.3, count: 704 }, { label: 'Cost', share: 10.4 }] } }
  const text = objectionAnswer(real)
  assert.match(text, /1\. \*\*Trust \/ looks like a scam\*\*: 70\.3% \(704 people\)/)
  assert.match(text, /2\. \*\*Cost\*\*: 10\.4%$/m)
  assert.match(text, /Simulated/)
  assert.match(objectionAnswer({}), /no objections/)
  const seg = segmentAnswer({ marketing: { by_segment: [{ key: 'Students', n: 214, convert_yes: 0 }, { key: 'Kenya', n: 144, convert_yes: 2.8 }, { key: 'India', n: 142, convert_yes: 1.4 }] } })
  assert.match(seg, /1\. \*\*Kenya\*\*: 2\.8% would buy \(144 people\)/)
  assert.match(seg, /Close call: \*\*Kenya\*\*/)
  const clear = segmentAnswer({ marketing: { by_segment: [{ key: 'A', n: 50, convert_yes: 20 }, { key: 'B', n: 50, convert_yes: 5 }] } })
  assert.match(clear, /\*\*A\*\* leads in this simulated run/)
  assert.match(segmentAnswer(null), /no audience breakdown/)
})

test('the run behind an assistant message', () => {
  assert.equal(messageRun({ role: 'assistant', run_card: { run: 'a' } }), 'a')
  assert.equal(messageRun({ role: 'assistant', audience_run: 'b' }), 'b')
  assert.equal(messageRun({ role: 'assistant', reportBrowser: { run: 'c' } }), 'c')
  assert.equal(messageRun({ role: 'assistant', artifacts: [{ run: 'd', file: 'x.json' }] }), 'd')
  assert.equal(messageRun({ role: 'assistant', agent: { cards: [{ type: 'tool' }, { type: 'artifact', kind: 'view', run: 'e' }] } }), 'e')
  assert.equal(messageRun({ role: 'user', run_card: { run: 'a' } }), '')
  assert.equal(messageRun({ role: 'assistant', content: 'hi' }), '')
})
