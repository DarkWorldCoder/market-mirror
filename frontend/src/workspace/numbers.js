// Counts use the reader's locale, matching the run page and social feed. Pass a
// locale only in tests, where the machine setting must not decide the result.
export function formatCount(value, locale) {
  return Number(value || 0).toLocaleString(locale)
}
