import test from 'node:test'
import assert from 'node:assert/strict'
import { DEFAULT_MAP_CONFIG, allowedBasemap, availableBasemaps } from '../mapConfig.js'

test('the default allows every map type', () => {
  assert.deepEqual(availableBasemaps(DEFAULT_MAP_CONFIG), ['auto', 'satellite', 'dark', 'simple'])
})

test('tiles off leaves only the offline map', () => {
  const off = { mode: 'off', streets: null, dark: null, satellite: null, glyphs: null }
  assert.deepEqual(availableBasemaps(off), ['simple'])
  assert.equal(allowedBasemap('satellite', off), 'simple')
})

test('a custom server without satellite drops that choice', () => {
  const custom = { mode: 'custom', streets: 'https://tiles.example.test/style.json', dark: 'https://tiles.example.test/style.json', satellite: null }
  assert.deepEqual(availableBasemaps(custom), ['auto', 'dark', 'simple'])
  assert.equal(allowedBasemap('satellite', custom), 'auto')
  assert.equal(allowedBasemap('dark', custom), 'dark')
})
