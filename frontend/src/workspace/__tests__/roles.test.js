import assert from 'node:assert/strict'
import test from 'node:test'
import { ROLES, roleHint, roleLabel } from '../roles.js'

test('role labels are capitalised', () => {
  assert.deepEqual(ROLES.map(roleLabel), ['Owner', 'Editor', 'Viewer'])
})

test('every role has a hint, and unknown roles have none', () => {
  for (const role of ROLES) assert.match(roleHint(role), /^[A-Z][a-z]+: /)
  assert.equal(roleHint('unknown'), '')
})
