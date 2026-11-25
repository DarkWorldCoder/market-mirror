import assert from 'node:assert/strict'
import test from 'node:test'
import { OFFLINE_MESSAGE, isNetworkError, requestErrorText } from '../network.js'

test('a failed fetch becomes a plain-language message', () => {
  assert.equal(isNetworkError(new TypeError('Failed to fetch')), true)
  assert.equal(isNetworkError(new Error('NetworkError when attempting to fetch resource.')), true)
  assert.equal(isNetworkError(new Error('Request failed (500)')), false)
  assert.equal(requestErrorText(new TypeError('Failed to fetch')), OFFLINE_MESSAGE)
  assert.equal(requestErrorText(new Error('Run not found')), 'Run not found')
})
