import test from 'node:test'
import assert from 'node:assert/strict'
import { featureCatalog, featureGroups, loadCustomSkills, searchFeatures, customSkillError } from '../featureCatalog.js'

test('saved custom templates join all built-ins, preserve exact instructions, and disappear after deletion', async () => {
 const originalFetch = globalThis.fetch, originalLocation = globalThis.location, originalStorage = globalThis.sessionStorage
 globalThis.location = { hash: '' }
 globalThis.sessionStorage = { getItem: () => 'skills-test' }
 const instruction = 'Review the supplied renewal evidence.\nKeep every source citation.'
 const custom = { id: 'skill_' + 'a'.repeat(32), name:'Renewal review', description:'Review account renewal evidence', instructions:instruction, group:'Custom skills', source_url:'https://github.com/example/skills' }
 let values = [custom]
 globalThis.fetch = async (path, options) => {
  assert.equal(path, '/api/workspace/skills')
  assert.equal(options.headers['X-Setup-Token'], 'skills-test')
  return new Response(JSON.stringify({ success:true, data:values }), { headers:{'Content-Type':'application/json'} })
 }
 try {
  const builtIns = featureCatalog.length
  assert.equal(searchFeatures('/new-experiment')[0].action, 'experiment')
  assert.equal(searchFeatures('/analyze').find(item => item.command === '/analyze').action, 'analyze')
  await loadCustomSkills()
  assert.equal(featureCatalog.length, builtIns + 1)
  assert.equal(searchFeatures('/renewal')[0].prompt, instruction)
  assert.equal(searchFeatures('/renewal')[0].sourceUrl, custom.source_url)
  assert.equal(searchFeatures('/renewal')[0].custom, true)
  assert.equal(searchFeatures(searchFeatures('/renewal')[0].command)[0].prompt, instruction)
  assert.ok(featureGroups.includes('Custom skills'))
  assert.equal(new Set(featureCatalog.map(item => item.id)).size, builtIns + 1)
  values = []
  await loadCustomSkills(true)
  assert.equal(featureCatalog.length, builtIns)
  assert.equal(searchFeatures('/renewal').length, 0)
  assert.ok(!featureGroups.includes('Custom skills'))
  assert.equal(customSkillError.value, '')
 } finally { globalThis.fetch = originalFetch; globalThis.location = originalLocation; globalThis.sessionStorage = originalStorage }
})
