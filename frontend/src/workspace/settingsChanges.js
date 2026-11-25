// Settings are edited per tab but saved together: this lists the sections whose
// draft differs from the last saved state, so only those are sent.
const text = (value) => String(value ?? '')
const number = (value) => (value === '' || value === null || value === undefined ? null : Number(value))

export function changedSections(draft, saved) {
  if (!saved) return []
  const changed = []
  const models = draft.models || {}
  if (models.api_key || ['provider', 'model', 'base_url', 'pool'].some((key) => text(models[key]) !== text(saved.llm?.[key]))) changed.push('models')

  const spending = draft.spending || {}
  if (['process_limit_usd', 'input_price_usd_per_mtok', 'output_price_usd_per_mtok'].some((key) => number(spending[key]) !== number(saved.spending?.[key]))) changed.push('spending')

  const memory = draft.memory || {}
  if (memory.zep_api_key || ['backend', 'embeddings', 'extract_activity', 'cognee_url'].some((key) => text(memory[key]) !== text(saved.memory?.[key]))) changed.push('memory')

  const jev = draft.jev || {}
  if (jev.api_key || ['route', 'model', 'labels', 'ssr_engine'].some((key) => text(jev[key]) !== text(saved.jev?.[key])) ||
    ['parallel', 'timeout', 'retries'].some((key) => number(jev[key]) !== number(saved.jev?.[key]))) changed.push('jev')

  return changed
}
