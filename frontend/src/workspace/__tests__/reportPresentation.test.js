import test from 'node:test'
import assert from 'node:assert/strict'
import { reportInfo, preferredReport, tableRows, readableLabel, presentReport } from '../reportPresentation.js'
test('ordinary reports have readable names and source files remain addressable', () => {
 assert.equal(reportInfo('agent_stats.json').title, 'Persona activity')
 assert.equal(reportInfo('run_manifest.json').category, 'Advanced')
 assert.equal(reportInfo('future_custom_study.json').file, 'future_custom_study.json')
 assert.equal(reportInfo('future_custom_study.json').title, 'Future custom study')
})
test('the overview is opened before technical metadata or arbitrary file order', () => {
 assert.equal(preferredReport(['actions.json', 'run_manifest.json', 'summary.json']), 'summary.json')
 assert.equal(preferredReport(['run_manifest.json', 'survey.json']), 'survey.json')
 assert.equal(preferredReport([]), '')
})
test('saved funnel tuples become chart rows without changing zero or values', () => {
 assert.deepEqual(tableRows([['Aware', 40], ['Converted', 0]]), [{ label: 'Aware', count: 40 }, { label: 'Converted', count: 0 }])
 assert.equal(tableRows([['Bad', 'not numeric']]), null)
 assert.equal(readableLabel('mean_click_probability'), 'Mean click probability')
})
test('feed-test exposures are labelled per person and marked simulated, never called Views', () => {
 const report = presentReport('feed_test.json', { creatives: [{ id: 'a' }], personas_tested: 2999, exposures: 1,
   summary: { per_creative: { a: { expected_ctr: 2.5, impressions: 3000 } } } })
 const card = report.cards.find((c) => c.label === 'Exposures per person')
 assert.ok(card, 'the per-person value has a clear label')
 assert.equal(card.value, '1')
 assert.match(card.note, /simulated/i)
 assert.ok(!report.cards.some((c) => c.label === 'Views'), 'no card claims a total views count the data does not hold')
})
