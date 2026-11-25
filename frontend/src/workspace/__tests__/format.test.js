import assert from 'node:assert/strict'
import test from 'node:test'
import { formatDate, formatMoney, formatNumber, setFormatLocale } from '../format.js'

test('numbers, money and dates use the configured locale', () => {
  setFormatLocale('en')
  assert.equal(formatNumber(1234.5), '1,234.5')
  assert.equal(formatMoney(12.5), '$12.50')
  assert.match(formatDate(new Date(2026, 10, 24)), /Nov 24, 2026/)

  setFormatLocale('de')
  assert.equal(formatNumber(1234.5), '1.234,5')
  assert.match(formatDate(new Date(2026, 10, 24)), /24\. Nov\. 2026/)

  setFormatLocale('en')
})
