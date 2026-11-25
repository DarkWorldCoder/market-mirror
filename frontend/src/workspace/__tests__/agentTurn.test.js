import assert from 'node:assert/strict'
import test from 'node:test'
import { agentReply, runAgentTurn } from '../../components/workspace/agent/agentTurn.js'

test('an agent turn explains a dropped connection', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch') })
  const message = agentReply('reply')

  assert.equal(await runAgentTurn({ message, body: {} }), null)
  assert.equal(message.agent.status, 'error')
  assert.equal(message.agent.error.message, 'The connection was interrupted. Try again.')
})
