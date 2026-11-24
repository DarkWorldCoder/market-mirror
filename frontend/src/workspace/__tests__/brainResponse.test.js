import test from 'node:test'
import assert from 'node:assert/strict'
import { BRAIN_LABEL, brainOption, brainRows, clock, peakText } from '../brainResponse.js'

globalThis.document = { querySelector: () => ({}), documentElement: {} }
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' })

const summary = {
  kind: 'video', seconds: [0, 1, 2, 3],
  groups: {
    visual: { label: 'visual areas', z: [1, 0, -1, 0], peaks: [{ start: 0, end: 0, peak: 0, z: 1 }] },
    hearing: { label: 'hearing areas', z: [0, 1.5, 0, -1.5], peaks: [{ start: 1, end: 2, peak: 1, z: 1.5 }] },
    cortex: { label: 'whole cortex', z: [0, 0, 0, 0], peaks: [] }
  }
}

test('rows come from brain_response.json, else from feed-test creatives', () => {
  const file = { creatives: [{ id: 'a', status: 'skipped', reason: 'no image input' }] }
  assert.equal(brainRows(file, null)[0].reason, 'no image input')
  const feed = { creatives: [{ id: 'v1', name: 'Launch', brain_response: { summary, line: 'hearing areas peak at 0:01-0:02.' } }, { id: 'x' }] }
  const rows = brainRows(null, feed)
  assert.equal(rows.length, 1)
  assert.equal(rows[0].status, 'ok')
  assert.equal(rows[0].kind, 'video')
  assert.deepEqual(brainRows(null, null), [])
})

test('chart option draws one line per group with the cortex dashed', () => {
  const opt = brainOption(summary)
  assert.deepEqual(opt.series.map((s) => s.name), ['visual areas', 'hearing areas', 'whole cortex'])
  assert.equal(opt.series[2].lineStyle.type, 'dashed')
  assert.deepEqual(opt.series[1].data[1], [1, 1.5])
  assert.equal(opt.xAxis.axisLabel.formatter(65), '1:05')
  assert.equal(brainOption({ seconds: [0], groups: {} }), null)
})

test('peaks read as clock spans and the label is the agreed wording', () => {
  assert.deepEqual(peakText(summary), ['visual areas: 0:00', 'hearing areas: 0:01-0:02'])
  assert.equal(clock(7), '0:07')
  assert.match(BRAIN_LABEL, /not attention, feelings, memory or buying\. Not validated for ads\.$/)
})
