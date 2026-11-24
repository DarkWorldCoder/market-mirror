import test from 'node:test'
import assert from 'node:assert/strict'
import { OTHER, briefErrors, choiceOf, ideasErrors, isWebUrl } from '../setupFields.js'
import { claudeLoginFallback, modelStatus, rejectedModel } from '../../components/agent-elements/input/model-status.js'

const ready = () => ({
  name: 'FitLoop', product: 'Home workouts for parents', source_url: '', facts: '',
  variants: [{ label: 'A', text: 'Ten minutes a day' }, { label: 'B', text: 'Workouts that fit nap time' }],
  audience: 'Busy parents', country: 'Nepal', language: 'English', people: 20, platform: 'instagram', ad_budget: null, currency: 'USD'
})

test('a complete brief and ideas have no messages', () => {
  assert.deepEqual(briefErrors(ready()), {})
  assert.deepEqual(ideasErrors(ready()), {})
})

test('required brief fields and the page address are checked inline', () => {
  const errors = briefErrors({ ...ready(), name: ' ', product: '', source_url: 'your-product' })
  assert.deepEqual(Object.keys(errors), ['name', 'product', 'source_url'])
  assert.equal(briefErrors({ ...ready(), source_url: 'https://fitloop.example/pricing' }).source_url, undefined)
  assert.ok(!isWebUrl('javascript:alert(1)'))
  assert.ok(!isWebUrl('https://user:pass@example.com'))
  assert.ok(isWebUrl('http://localhost:5173'))
})

test('ideas follow the limits the backend enforces', () => {
  assert.match(ideasErrors({ ...ready(), people: 3 }).people, /between 4 and 60/)
  assert.match(ideasErrors({ ...ready(), people: 61 }).people, /between 4 and 60/)
  assert.match(ideasErrors({ ...ready(), people: '' }).people, /whole number/)
  assert.match(ideasErrors({ ...ready(), people: 7.5 }).people, /whole number/)
  assert.match(ideasErrors({ ...ready(), ad_budget: -1 }).ad_budget, /0 or more/)
  assert.equal(ideasErrors({ ...ready(), ad_budget: '' }).ad_budget, undefined)
  assert.equal(ideasErrors({ ...ready(), platform: 'myspace' }).platform, 'Choose a channel.')
  const same = ready()
  same.variants[1].text = ' Ten minutes a day '
  assert.match(ideasErrors(same).text1, /identical/)
  const missing = ideasErrors({ ...ready(), country: '', language: '', audience: '' })
  assert.deepEqual(Object.keys(missing).sort(), ['audience', 'country', 'language'])
})

test('saved countries outside the list stay editable as another country', () => {
  assert.equal(choiceOf('Nepal', ['Nepal']), 'Nepal')
  assert.equal(choiceOf('Bhutan', ['Nepal']), OTHER)
  assert.equal(choiceOf('', ['Nepal']), '')
})

test('model picker statuses and the Claude Code fallback', () => {
  const models = [
    { id: 'api', provider: 'claude', status: 'key_rejected', available: false },
    { id: 'haiku', model: 'haiku', connection_backend: 'claude', status: 'connected', available: true },
    { id: 'sonnet', model: 'sonnet', connection_backend: 'claude', status: 'connected', available: true },
    { id: 'codex', connection_backend: 'codex', status: 'connect_on_first_use', available: true }
  ]
  assert.deepEqual(models.map(m => modelStatus(m).label), ['Key rejected', 'Connected', 'Connected', 'Connects on first use'])
  assert.equal(modelStatus({ available: false }).id, 'needs_connection')
  assert.equal(modelStatus({}).label, 'Key saved')
  assert.equal(rejectedModel(models).id, 'api')
  assert.equal(claudeLoginFallback(models).id, 'sonnet')
  assert.equal(claudeLoginFallback([{ id: 'c', connection_backend: 'claude', status: 'connect_on_first_use', available: true }]).id, 'c')
  assert.equal(claudeLoginFallback([{ id: 'x', connection_backend: 'claude', status: 'needs_connection', available: false }]), null)
})
