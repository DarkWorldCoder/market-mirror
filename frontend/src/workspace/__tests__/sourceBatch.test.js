import assert from 'node:assert/strict'
import test from 'node:test'
import { sourceFileProblem, summarizeBatch } from '../sourceBatch.js'

const file = (name, size = 10) => ({ name, size })

test('sourceFileProblem names the first limit a file breaks', () => {
  assert.equal(sourceFileProblem(file('brief.md'), 0), '')
  assert.equal(sourceFileProblem(file('deck.pdf'), 0), 'format')
  assert.equal(sourceFileProblem(file('huge.txt', 100001), 0), 'too large')
  assert.equal(sourceFileProblem(file('brief.md'), 10), 'source limit')
})

test('summarizeBatch reports how many were added and why others were skipped', () => {
  assert.equal(summarizeBatch(3, 3, []), 'Added 3 of 3.')
  assert.equal(summarizeBatch(3, 5, ['a.pdf (format)', 'b.txt (too large)']),
    'Added 3 of 5. Skipped: a.pdf (format), b.txt (too large).')
})
