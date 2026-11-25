import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick } from 'vue'
import { createPinStore } from '../pins.js'

function fakeStorage(initial = {}) {
  const map = new Map(Object.entries(initial))
  return { getItem: (key) => (map.has(key) ? map.get(key) : null), setItem: (key, value) => map.set(key, String(value)) }
}

function fakeFetcher(server, calls) {
  return async (path, options = {}) => {
    calls.push({ path, options })
    if (options.method === 'PUT') {
      server.pins = options.body.pins
      return { pins: [...server.pins] }
    }
    return { pins: [...server.pins] }
  }
}

test('switching workspace shows that workspace\'s pins, not the previous one', async () => {
  const storage = fakeStorage({
    'mm-pinned-runs:A': JSON.stringify(['a-run']),
    'mm-pinned-runs:B': JSON.stringify(['b-run']),
    'mm-pinned-runs-imported:A': '1',
    'mm-pinned-runs-imported:B': '1',
  })
  const store = createPinStore(storage)
  const calls = []
  await store.loadPins('A', fakeFetcher({ pins: ['a-run'] }, calls))
  assert.deepEqual(store.pins.value, ['a-run'])
  await store.loadPins('B', fakeFetcher({ pins: ['b-run'] }, calls))
  assert.deepEqual(store.pins.value, ['b-run'])
})

test('loading pins that match the server sends no PUT', async () => {
  const storage = fakeStorage({
    'mm-pinned-runs:A': JSON.stringify(['a-run']),
    'mm-pinned-runs-imported:A': '1',
  })
  const store = createPinStore(storage)
  const calls = []
  await store.loadPins('A', fakeFetcher({ pins: ['a-run'] }, calls))
  await nextTick()
  assert.equal(calls.filter((call) => call.options.method === 'PUT').length, 0)
})

test('a user change after loading is saved', async () => {
  const storage = fakeStorage({ 'mm-pinned-runs:A': '[]', 'mm-pinned-runs-imported:A': '1' })
  const store = createPinStore(storage)
  const calls = []
  await store.loadPins('A', fakeFetcher({ pins: [] }, calls))
  store.togglePin('new-run')
  await nextTick()
  assert.equal(calls.filter((call) => call.options.method === 'PUT').length, 1)
})
