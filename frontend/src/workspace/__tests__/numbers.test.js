import assert from 'node:assert/strict'
import test from 'node:test'
import { formatCount } from '../numbers.js'

test('formatCount follows the locale it is given', () => {
  assert.equal(formatCount(2999, 'en-US'), '2,999')
  assert.equal(formatCount(2999, 'de-DE'), '2.999')
  assert.equal(formatCount(null, 'en-US'), '0')
})
