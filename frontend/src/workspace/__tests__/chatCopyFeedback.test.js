import assert from 'node:assert/strict'
import test from 'node:test'
import { effectScope } from 'vue'
import { useChatCopyFeedback } from '../chatCopyFeedback.js'

test('each copied message gets its own two-second feedback window', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const contents = []
  const clipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: async (content) => contents.push(content) }
  })
  t.after(() => {
    if (clipboard) Object.defineProperty(navigator, 'clipboard', clipboard)
    else delete navigator.clipboard
  })
  const scope = effectScope()
  t.after(() => scope.stop())
  const { copiedMessage, copyMessage } = scope.run(() => useChatCopyFeedback(() => assert.fail('copy failed')))

  await copyMessage({ id: 'first', content: 'First reply' })
  assert.equal(copiedMessage.value, 'first')
  t.mock.timers.tick(1000)
  await copyMessage({ id: 'second', content: 'Second reply' })
  t.mock.timers.tick(1000)
  assert.equal(copiedMessage.value, 'second')
  t.mock.timers.tick(1000)
  assert.equal(copiedMessage.value, '')
  assert.deepEqual(contents, ['First reply', 'Second reply'])

  await copyMessage({ id: 'third', content: 'Third reply' })
  scope.stop()
  t.mock.timers.tick(2000)
  assert.equal(copiedMessage.value, 'third', 'the disposed scope has no pending timer')
})
