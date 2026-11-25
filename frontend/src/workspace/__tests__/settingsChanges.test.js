import assert from 'node:assert/strict'
import test from 'node:test'
import { changedSections } from '../settingsChanges.js'

const saved = {
  llm: { provider: 'openai', model: 'gpt', base_url: 'https://api.openai.com/v1', pool: '' },
  spending: { process_limit_usd: 5, input_price_usd_per_mtok: null, output_price_usd_per_mtok: null },
  memory: { backend: 'local', embeddings: false, extract_activity: false, cognee_url: '' },
  jev: { route: 'typesafe', model: '', parallel: 4, timeout: 60, retries: 3, labels: 'auto', ssr_engine: 'embeddings' },
}

test('an untouched draft has no changed sections', () => {
  const draft = { models: { ...saved.llm, api_key: '' }, spending: { ...saved.spending }, memory: { ...saved.memory, zep_api_key: '' }, jev: { ...saved.jev, api_key: '' } }
  assert.deepEqual(changedSections(draft, saved), [])
})

test('edits on two tabs are both reported', () => {
  const draft = { models: { ...saved.llm, model: 'gpt-mini', api_key: '' }, spending: { ...saved.spending, process_limit_usd: '9' }, memory: { ...saved.memory, zep_api_key: '' }, jev: { ...saved.jev, api_key: '' } }
  assert.deepEqual(changedSections(draft, saved), ['models', 'spending'])
})

test('a typed key counts as a change, an empty one does not', () => {
  const base = { models: { ...saved.llm, api_key: '' }, spending: { ...saved.spending }, memory: { ...saved.memory, zep_api_key: '' }, jev: { ...saved.jev, api_key: '' } }
  assert.deepEqual(changedSections(base, saved), [])
  assert.deepEqual(changedSections({ ...base, models: { ...base.models, api_key: 'sk-test' } }, saved), ['models'])
  assert.deepEqual(changedSections({ ...base, jev: { ...base.jev, api_key: 'sk-test' } }, saved), ['jev'])
})
