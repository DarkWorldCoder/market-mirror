import assert from 'node:assert/strict'
import test from 'node:test'

globalThis.window = { dispatchEvent() {} }
const { account, accountError, loadAccount } = await import('../account.js')

const response = (status) => new Response(JSON.stringify({ success: false, error: 'nope' }), { status, headers: { 'Content-Type': 'application/json' } })

test('a 404 session route still means local mode', async () => {
  account.value = { mode: 'unknown' }
  globalThis.fetch = async () => response(404)
  await loadAccount()
  assert.equal(account.value.mode, 'local')
  assert.equal(accountError.value, '')
})

test('a 500 keeps the mode unknown and asks to retry', async () => {
  account.value = { mode: 'unknown' }
  globalThis.fetch = async () => response(500)
  await loadAccount()
  assert.equal(account.value.mode, 'unknown')
  assert.match(accountError.value, /Cannot reach the server/)
})

test('a network failure is not local mode either', async () => {
  account.value = { mode: 'unknown' }
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch') }
  await loadAccount()
  assert.equal(account.value.mode, 'unknown')
  assert.match(accountError.value, /Cannot reach the server/)
})
