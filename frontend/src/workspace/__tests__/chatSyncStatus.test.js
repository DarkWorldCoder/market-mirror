import assert from 'node:assert/strict'
import test from 'node:test'
import { syncStatusText } from '../chatSync.js'

test('syncStatusText names the save state and keeps the reason', () => {
  assert.equal(syncStatusText('synced', ''), '')
  assert.equal(syncStatusText('syncing', ''), 'Saving chats…')
  assert.match(syncStatusText('offline', 'Saved in this browser only. Failed to fetch'), /^Saved in this browser only/)
  assert.match(syncStatusText('read-only', 'You can read this workspace.'), /read this workspace/)
  assert.equal(syncStatusText('offline', ''), 'Saved in this browser only.')
})
