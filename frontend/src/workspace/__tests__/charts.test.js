import test from 'node:test'
import assert from 'node:assert/strict'
import { creativesOption, decisionText, decisionTone, objectionsOption, palette, peopleOption, sampleCount, verdictColor } from '../charts.js'

// charts.js reads its colours from CSS custom properties on .ws; give it a minimal stand-in for the browser.
const tokens = { '--accent': '#70530d', '--maybe': '#906d1c', '--yes': '#347556', '--no': '#a94f58', '--data': '#4b5563', '--warm': '#a55c32' }
globalThis.document = { querySelector: () => ({}), documentElement: {} }
globalThis.getComputedStyle = () => ({ getPropertyValue: (name) => tokens[name] || '' })

test('small samples read as counts, large ones keep the percentage', () => {
  assert.deepEqual(sampleCount(3.6, 28), { count: 1, n: 28, text: '1 of 28', pct: '3.6%' })
  assert.equal(sampleCount(71.4, 28).text, '20 of 28')
  assert.equal(sampleCount(0, 12).text, '0 of 12')
  assert.equal(sampleCount(100, 99).text, '99 of 99')
  assert.equal(sampleCount(140, 10).count, 10, 'clamped to n')
  assert.equal(sampleCount(25, 100), null)
  assert.equal(sampleCount(25, 3000), null)
  assert.equal(sampleCount(25, undefined), null)
  assert.equal(sampleCount(undefined, 20), null)
  assert.equal(sampleCount(25, 0), null)
})

test('decision tone and text follow the saved decision', () => {
  assert.equal(decisionTone('go'), 'go')
  assert.equal(decisionTone('Launch'), 'go')
  assert.equal(decisionTone('iterate'), 'iterate')
  assert.equal(decisionTone('no_go'), 'stop')
  assert.equal(decisionTone('no-go'), 'stop')
  assert.equal(decisionTone(''), 'iterate')
  assert.equal(decisionText('no_go'), 'No go')
  assert.equal(decisionText('iterate'), 'Iterate')
  assert.equal(decisionText(null), '')
})

test('neutral bars use the data colour, not the accent that reads as maybe', () => {
  const p = palette()
  assert.equal(p.data, '#4b5563')
  assert.notEqual(p.data, p.maybe)
  const people = peopleOption([{ country: 'India' }, { country: 'India' }, { country: 'Kenya' }, { country: 'Kenya', kind: 'brand' }])
  assert.equal(people.series[0].itemStyle.color, p.data)
  assert.deepEqual(people.series[0].data, [1, 2])
  const objections = objectionsOption({ objections: [{ label: 'Price', share: 40 }] })
  assert.equal(objections.series[0].itemStyle.color, p.data)
  const ads = creativesOption({ summary: { per_creative: { a: { expected_ctr: 2 }, b: { expected_ctr: 5 } } } })
  const colours = ads.series[0].data.map((d) => d.itemStyle.color)
  assert.deepEqual(colours, [p.data, p.warm], 'best ad highlighted, the rest neutral')
})

test('response dots take the verdict colour; anything else is neutral', () => {
  const p = palette()
  assert.equal(verdictColor('yes', p), p.yes)
  assert.equal(verdictColor('Maybe', p), p.maybe)
  assert.equal(verdictColor('no', p), p.no)
  assert.equal(verdictColor(undefined, p), p.data)
  assert.equal(verdictColor('unsure', p), p.data)
})
