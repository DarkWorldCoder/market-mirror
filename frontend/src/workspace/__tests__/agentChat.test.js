import test from 'node:test'
import assert from 'node:assert/strict'
import { agentChatEnabled, agentHistory, answerLabel, compareFromCards, consumeAgentStream, costLabel, durationText, formErrors, isSimulated, lastLines, markAnswered, newTurnState, parseList, reduceAgentEvent, segmentFlags, segmentTotals, stepRows, usd } from '../agentChat.js'

const encoder = new TextEncoder()
const response = (text) => new Response(new ReadableStream({ start(c) { for (const b of encoder.encode(text)) c.enqueue(Uint8Array.of(b)); c.close() } }), { headers: { 'Content-Type': 'text/event-stream' } })

test('agent stream delivers every event in order and returns the done payload', async () => {
  const seen = []
  const text = ': keep-alive\n\nevent: plan\ndata: {"phase":"test"}\n\nevent: tool_start\r\ndata: {"id":"1","tool":"market_test"}\r\n\r\nevent: approval_request\ndata: {"id":"ap_1","kind":"spend"}\n\nevent: done\ndata: {"status":"waiting","message":"नमस्ते"}'
  const done = await consumeAgentStream(response(text), { onEvent: (name, data) => seen.push(name) })
  assert.deepEqual(seen, ['plan', 'tool_start', 'approval_request', 'done'])
  assert.equal(done.status, 'waiting')
  assert.equal(done.message, 'नमस्ते')
})

test('agent stream errors carry status, code and actions; early close fails', async () => {
  await assert.rejects(consumeAgentStream(response('event: error\ndata: {"message":"Your Claude key was rejected. Nothing was spent.","status":401,"code":"auth","actions":[{"id":"open_model_settings","label":"Open model settings"}]}\n\n')),
    (e) => e.status === 401 && e.code === 'auth' && e.actions[0].id === 'open_model_settings' && /Nothing was spent/.test(e.message))
  await assert.rejects(consumeAgentStream(response('event: plan\ndata: {"phase":"setup"}\n\n')), /closed before/)
})

test('reducer builds tool, progress, artifact and approval cards', () => {
  const s = newTurnState()
  reduceAgentEvent(s, 'plan', { phase: 'audience', offers: ['Turn reviews.csv into grounded personas'], auto: [{ tool: 'analytics_audience', reason: 'Sizing it' }] })
  reduceAgentEvent(s, 'tool_start', { id: 't1', tool: 'market_test', label: 'Market test', cost: 'spend', simulated: true, arguments: { config: {} } })
  reduceAgentEvent(s, 'tool_progress', { id: 't1', log_tail: Array.from({ length: 40 }, (_, i) => `line ${i}`), elapsed_s: 10 })
  reduceAgentEvent(s, 'tool_result', { id: 't1', status: 'completed', duration_ms: 2500, preview: 'x'.repeat(5000) })
  reduceAgentEvent(s, 'artifact', { kind: 'compare', compare: { a: 'r1', b: 'r2' }, simulated: true })
  reduceAgentEvent(s, 'approval_request', { id: 'ap_9', kind: 'spend', options: [{ value: 'run', label: 'Run' }] })
  reduceAgentEvent(s, 'done', { status: 'waiting', message: '' })
  const toolCard = s.cards.find((c) => c.type === 'tool')
  assert.equal(s.phase, 'audience')
  assert.equal(toolCard.log.length, 15)
  assert.equal(toolCard.log.at(-1), 'line 39')
  assert.equal(toolCard.status, 'completed')
  assert.ok(toolCard.preview.length <= 2000)
  assert.deepEqual(compareFromCards(s.cards), { a: 'r1', b: 'r2' })
  assert.equal(s.pending.id, 'ap_9')
  markAnswered(s, 'ap_9', 'Run')
  assert.equal(s.pending, null)
  assert.equal(s.cards.find((c) => c.type === 'approval').answered, 'Run')
  reduceAgentEvent(s, 'error', { message: 'down', status: 503, actions: [] })
  assert.equal(s.status, 'error')
})

test('declined results without a start still render as a tool card', () => {
  const s = reduceAgentEvent(newTurnState(), 'tool_result', { tool: 'intake', status: 'declined', result: { message: 'The user chose Stop.' } })
  assert.equal(s.cards[0].status, 'declined')
  assert.equal(s.cards[0].preview, 'The user chose Stop.')
})

test('the Simulated badge comes from the tool, not from text', () => {
  assert.equal(isSimulated('compare_runs'), true)
  assert.equal(isSimulated('ads_import'), false)
  assert.equal(isSimulated('ads_import', false), false)
  assert.equal(isSimulated('results', false), true)
})

test('labels, money, durations and steps', () => {
  assert.equal(costLabel('spend'), 'Uses model calls')
  assert.equal(costLabel('outside'), 'Contacts the web')
  assert.equal(usd(0.425), '$0.42')
  assert.equal(usd(null), 'unknown')
  assert.equal(durationText(850), '850 ms')
  assert.equal(durationText(125000), '2 min 5 s')
  assert.deepEqual(stepRows({ people: 20, survey: 0, report: 12 }).map((r) => r.label), ['Create the people', 'Report'])
  assert.deepEqual(lastLines(['a', 'b', 'c'], 2), ['b', 'c'])
})

test('form validation', () => {
  const fields = [{ name: 'spec.type', type: 'select', required: true, options: [{ value: 'price' }] }, { name: 'n', type: 'number', required: true }, { name: 'note', type: 'text' }]
  assert.deepEqual(formErrors(fields, {}), { 'spec.type': 'Required', n: 'Required' })
  assert.deepEqual(formErrors(fields, { 'spec.type': 'ad', n: 'ten' }), { 'spec.type': 'Choose an option', n: 'Enter a number' })
  assert.deepEqual(formErrors(fields, { 'spec.type': 'price', n: '12' }), {})
})

test('audience totals and instant fit flags', () => {
  const segs = [{ label: 'Parents', count: 12, country: 'India' }, { label: 'Dads', count: 6, country: 'India' }, { label: '', count: 50 }]
  assert.deepEqual(segmentTotals(segs), { people: 18, segments: 2, countries: 1 })
  assert.deepEqual(segmentFlags(segs).map((f) => f.code), ['small_segments', 'less_covered_markets'])
  assert.deepEqual(segmentFlags([{ label: 'US parents', count: 20, country: 'United States' }]), [])
  assert.deepEqual(parseList('instagram, whatsapp\nandroid'), ['instagram', 'whatsapp', 'android'])
})

test('history starts with the user and stays inside the limits', () => {
  const msgs = [{ role: 'assistant', content: 'hi' }, { role: 'user', content: 'a' }, { role: 'assistant', content: '' }, { role: 'user', content: 'b' }]
  assert.deepEqual(agentHistory(msgs), [{ role: 'user', content: 'a' }, { role: 'user', content: 'b' }])
  assert.equal(agentHistory(Array.from({ length: 60 }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', content: 'x' }))).length <= 25, true)
})

test('opt-out flag and answer labels', () => {
  assert.equal(agentChatEnabled({ getItem: () => '0' }), false)
  assert.equal(agentChatEnabled({ getItem: () => null }), true)
  assert.equal(agentChatEnabled({ getItem: () => { throw new Error('blocked') } }), true)
  assert.equal(answerLabel({ kind: 'spend', options: [{ value: 'people_first', label: 'Create people first' }] }, { decision: 'people_first' }), 'Create people first')
  assert.equal(answerLabel({ kind: 'form' }, { cancel: true }), 'Cancelled')
})
