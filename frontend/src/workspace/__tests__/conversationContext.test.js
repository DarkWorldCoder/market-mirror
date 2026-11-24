import test from 'node:test'
import assert from 'node:assert/strict'
import { buildConversationContext } from '../conversationContext.js'

test('uploaded evidence remains available for follow-ups and restored conversations', () => {
  const messages = [{ role: 'user', attachedFiles: [{ name: 'ga4.csv', text: 'country,users\nNepal,12' }] }, { role: 'assistant', content: 'Analysis' }, { role: 'user', content: 'Which country?' }]
  const context = buildConversationContext(JSON.parse(JSON.stringify(messages)))
  assert.equal(context.files.length, 1)
  assert.match(context.text, /Nepal,12/)
})

test('the same pending attachment and saved attachment are included once', () => {
  const file = { name: 'ads.json', text: '[{"spend":12}]' }
  assert.equal(buildConversationContext([{ attachedFiles: [file] }], { files: [file] }).files.length, 1)
})

test('recent evidence wins the context budget and omissions are reported', () => {
  const context = buildConversationContext([{ attachedFiles: [{ name: 'old.txt', text: 'x'.repeat(100) }] }], { files: [{ name: 'new.csv', text: 'a,b' }] }, 40)
  assert.equal(context.files[0].name, 'new.csv')
  assert.equal(context.omitted, 1)
  assert.ok(context.text.length <= 40)
})

test('missing or malformed attachment records do not become model context', () => {
  assert.equal(buildConversationContext([{ content: 'Hi' }, { attachedFiles: [{ name: 'bad.csv', text: null }] }]).text, '')
})

test('a question about an older capture retains that page when a newer one would fill the context budget', () => {
  const selected = { url: 'https://example.com/first', text: 'First page offer' }
  const recent = { url: 'https://example.com/second', text: 'Second page offer' }
  const context = buildConversationContext([
    { browser_observations: [selected] },
    { browser_observations: [{ ...selected, text: 'Revised offer' }, recent] }
  ], null, 70, selected)
  assert.deepEqual(context.files, [{ name: 'Page: https://example.com/first', text: selected.text }])
  assert.equal(context.omitted, 1)
})
