import assert from 'node:assert/strict'
import test from 'node:test'
import { chooseTheme } from '../theme.js'

test('a stored choice wins over the system', () => {
  assert.equal(chooseTheme('light', true), 'light')
  assert.equal(chooseTheme('dark', false), 'dark')
})

test('with no stored choice the system decides', () => {
  assert.equal(chooseTheme(null, true), 'dark')
  assert.equal(chooseTheme(null, false), 'light')
  assert.equal(chooseTheme('unexpected', true), 'dark')
})
