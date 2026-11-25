import assert from 'node:assert/strict'
import test from 'node:test'
import { agentReply, runAgentTurn } from '../../components/workspace/agent/agentTurn.js'

for (const detail of ['Failed to fetch', 'NetworkError when attempting to fetch resource.']) {
  test(`an agent turn explains a dropped connection: ${detail}`, async (t) => {
    t.mock.method(globalThis, 'fetch', async () => { throw new TypeError(detail) })
    const message = agentReply('reply')

    assert.equal(await runAgentTurn({ message, body: {} }), null)
    assert.equal(message.agent.status, 'error')
    assert.equal(message.agent.error.message, 'The connection was interrupted. Try again.')
  })
}
