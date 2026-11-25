import assert from 'node:assert/strict'
import test from 'node:test'
import { plural } from '../plural.js'

test('plural picks the English form for 0, 1 and 2', () => {
  const forms = { one: 'result', other: 'results' }
  assert.equal(plural(0, forms), 'results')
  assert.equal(plural(1, forms), 'result')
  assert.equal(plural(2, forms), 'results')
})

test('plural falls back to other when the rule is missing', () => {
  assert.equal(plural(1, { other: 'items' }), 'items')
})

test('plural only evaluates the selected form', () => {
  assert.equal(plural(2, { one: () => { throw new Error('one') }, other: 'items' }), 'items')
  assert.equal(plural(1, { one: () => 'item', other: () => { throw new Error('other') } }), 'item')
})
