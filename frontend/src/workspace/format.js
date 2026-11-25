// One place for user-facing numbers, currency and dates. The locale is set from
// vue-i18n at startup, so a screen never mixes en-US and the browser locale.
let locale = 'en'

export function setFormatLocale(value) {
  locale = value || 'en'
}

export function formatLocale() {
  return locale
}

export function formatNumber(value, options) {
  return new Intl.NumberFormat(locale, options).format(value)
}

export function formatDate(value, options = { day: 'numeric', month: 'short', year: 'numeric' }) {
  return new Intl.DateTimeFormat(locale, options).format(value instanceof Date ? value : new Date(value))
}

export function formatDateTime(value) {
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(value instanceof Date ? value : new Date(value))
}

export function formatMoney(value, currency = 'USD', options = {}) {
  return new Intl.NumberFormat(locale, { style: 'currency', currency, maximumFractionDigits: 4, ...options }).format(value || 0)
}
