import assert from 'node:assert/strict'
import test from 'node:test'
import { roleChangeNeedsConfirmation } from '../teamRoles.js'

test('own role and owner demotions ask first; other changes do not', () => {
  assert.equal(roleChangeNeedsConfirmation({ id: 'me', role: 'owner' }, 'editor', 'me'), true)
  assert.equal(roleChangeNeedsConfirmation({ id: 'other', role: 'owner' }, 'editor', 'me'), true)
  assert.equal(roleChangeNeedsConfirmation({ id: 'other', role: 'editor' }, 'viewer', 'me'), false)
  assert.equal(roleChangeNeedsConfirmation({ id: 'other', role: 'viewer' }, 'editor', 'me'), false)
})
