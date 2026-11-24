import test from 'node:test'
import assert from 'node:assert/strict'
import { actionsByRound, buildResponses, filterResponses, plainLabel, summarizeResponses } from '../responses.js'

const index = [{ agent_id: 1, name: 'Asha', segment: 'Students', country: 'India', city: 'Pune' }, { agent_id: 2, name: 'Ben', segment: 'Parents', country: 'Kenya' }]
const survey = { responses: [
  { agent_id: 1, answer: { would_convert: 'yes', quote: 'Looks useful', main_objection: 'Price', objection_type: 'price', would_change_mind: 'A discount' } },
  { agent_id: 2, answer: { would_convert: 'No', main_objection: 'Do not trust it', objection_type: 'trust' } },
  { agent_id: 3, answer: null },
  { agent_id: 4, answer: { would_convert: 'maybe' } }
] }
const feed = { sessions: [{ agent_id: 2, platform: 'tiktok', creative_id: 'ad1', ad: { thought: 'Another fitness ad', click: false } }, { agent_id: 1, ad: { thought: '' } }] }

test('builds rows from survey, feed and stream, skipping empty answers', () => {
  const rows = buildResponses({ survey, feed, stream: [{ agent_id: 1, text: 'Hmm' }], index })
  assert.equal(rows.length, 4)
  assert.deepEqual(rows.map((r) => r.source), ['survey', 'survey', 'feed', 'thought'])
  assert.equal(rows[0].name, 'Asha')
  assert.equal(rows[0].objection, 'Price')
  assert.equal(rows[1].verdict, 'no')
  assert.equal(rows[2].detail, 'tiktok · ad1')
})

test('filters by verdict, source, objection, segment and words', () => {
  const rows = buildResponses({ survey, feed, index })
  assert.equal(filterResponses(rows, { verdict: 'yes' }).length, 1)
  assert.equal(filterResponses(rows, { verdict: 'none' }).length, 1)
  assert.equal(filterResponses(rows, { source: 'feed' }).length, 1)
  assert.equal(filterResponses(rows, { objection: 'trust' })[0].name, 'Ben')
  assert.equal(filterResponses(rows, { segment: 'Students' }).length, 1)
  assert.equal(filterResponses(rows, { q: 'pune useful' }).length, 1)
  assert.equal(filterResponses(rows, { q: 'nothing like this' }).length, 0)
})

test('summarizes verdicts and objections', () => {
  const s = summarizeResponses(buildResponses({ survey, feed, index }))
  assert.deepEqual(s.verdicts, { yes: 1, maybe: 0, no: 1 })
  assert.equal(s.asked, 2)
  assert.deepEqual(s.objections.map((o) => o.key).sort(), ['price', 'trust'])
  assert.equal(plainLabel('price_value'), 'Price value')
})

test('groups actions by round into plain kinds', () => {
  const t = [{ round_num: 1, action_types: { CREATE_COMMENT: 3, LIKE_POST: 2, LIKE_COMMENT: 1, DO_NOTHING: 9 }, active_agents: [1, 2] }]
  const r = actionsByRound(t)
  assert.deepEqual(r.rounds, [1])
  assert.deepEqual(r.series.commented, [3])
  assert.deepEqual(r.series.liked, [3])
  assert.deepEqual(r.series['only read'], [9])
  assert.equal(r.series.posted, undefined)
  assert.deepEqual(r.active, [2])
})
