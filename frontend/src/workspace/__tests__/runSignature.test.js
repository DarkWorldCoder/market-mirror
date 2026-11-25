import assert from 'node:assert/strict'
import test from 'node:test'
import { runSignature } from '../overviewInsights.js'

test('runSignature changes when a run is added or its status changes', () => {
  const base = [{ name: 'a', status: 'done' }]
  assert.equal(runSignature(base), 'a:done')
  assert.equal(runSignature([...base, { name: 'b', status: 'running' }]), 'a:done|b:running')
  assert.notEqual(runSignature([{ name: 'a', status: 'running' }]), runSignature(base))
  assert.equal(runSignature([]), '')
})
