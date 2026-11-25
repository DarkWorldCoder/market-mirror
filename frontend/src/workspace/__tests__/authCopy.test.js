import assert from 'node:assert/strict'
import test from 'node:test'
import { canSignUp, signupSubheading } from '../authCopy.js'

test('sign-up is allowed only when open, first account, or invited', () => {
  assert.equal(canSignUp('open', false, false), true)
  assert.equal(canSignUp('invite', false, false), false)
  assert.equal(canSignUp('closed', false, false), false)
  assert.equal(canSignUp('closed', true, false), true)
  assert.equal(canSignUp('closed', false, true), true)
})

test('invite-only and closed explain different things', () => {
  assert.match(signupSubheading('invite'), /invite-only.*invitation link/)
  assert.match(signupSubheading('closed'), /closed.*Ask a workspace owner/)
})
