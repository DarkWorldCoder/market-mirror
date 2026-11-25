import test from 'node:test'
import assert from 'node:assert/strict'
import { chatFilename } from '../chatFilename.js'

test('Markdown filenames preserve letters, digits and combining marks across scripts', () => {
  for (const title of ['市场分析', 'बाज़ार', 'السوق', 'Q4-2026']) {
    assert.equal(chatFilename(title), title.normalize('NFC') + '.md')
  }
  assert.equal(chatFilename('/市场: 分析?/'), '市场_分析.md')
  assert.equal(chatFilename('𠀀'.repeat(61)), '𠀀'.repeat(60) + '.md')
})

test('titles without letters or numbers get a dated filename', () => {
  const date = new Date('2026-01-02T12:00:00Z')
  for (const title of ['', '?!', '🎶', '___---']) {
    assert.equal(chatFilename(title, date), 'marketmirror-chat-2026-01-02.md')
  }
})
