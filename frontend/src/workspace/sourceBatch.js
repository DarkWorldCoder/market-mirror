// Limits for project knowledge uploads, shared by the dialog and its tests.
export const SOURCE_LIMITS = { sources: 10, bytes: 100000, characters: 24000 }

// A file that cannot be saved, with a short reason for the batch summary.
export function sourceFileProblem(file, savedSources) {
  if (!/\.(md|txt|csv|json)$/i.test(file.name)) return 'format'
  if (file.size > SOURCE_LIMITS.bytes) return 'too large'
  if (savedSources >= SOURCE_LIMITS.sources) return 'source limit'
  return ''
}

export function summarizeBatch(added, total, skipped) {
  const base = `Added ${added} of ${total}.`
  return skipped.length ? `${base} Skipped: ${skipped.join(', ')}.` : base
}
