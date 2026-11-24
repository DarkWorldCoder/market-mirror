import test from 'node:test'
import assert from 'node:assert/strict'
import { buildConversationContext } from '../conversationContext.js'
import { parseCsv } from '../parseCsv.js'
import { funnelRows, pricingText, savedReportFor } from '../resultRouting.js'

test('CSV keeps quoted commas, quotes, line breaks and numeric values', () => {
  const data = parseCsv('name,quote,score\r\n"A, B","said ""yes""\nthen left",2.5\r\nC,no,0\r\n')
  assert.equal(data.length, 2)
  assert.equal(data[0].name, 'A, B')
  assert.equal(data[0].quote, 'said "yes"\nthen left')
  assert.equal(data[0].score, 2.5)
  assert.equal(data[1].score, 0)
})
test('CSV preserves duplicate columns and cells beyond the header', () => {
  const [row] = parseCsv('name,score,score\nA,1,2,extra')
  assert.equal(Object.values(row).length, 4)
  assert.deepEqual(Object.values(row), ['A', 1, 2, 'extra'])
})
test('funnel normalizes actual tuple exports and preserves zero', () => {
  assert.deepEqual(funnelRows([['Reached', 28], ['Converted', 0], ['Missing', null]]), [{label:'Reached',n:28},{label:'Converted',n:0}])
})
test('pricing renders nested threshold medians instead of object strings', () => {
  const text = pricingText({optimal:3,median:{price_cheap:2.99,price_expensive:15}}, 'USD')
  assert.match(text, /USD 2.99/)
  assert.match(text, /USD 15/)
  assert.doesNotMatch(text, /object Object/)
})
test('every exported artifact can be addressed by exact filename', () => {
  const files = ['analyst_panel.json','action_plan.json','survey_answers.csv','market_report.md','dashboard.html']
  for (const file of files) assert.equal(savedReportFor(`show ${file}`, files, {}).file, file)
})
test('natural report requests resolve only to available evidence', () => {
  assert.equal(savedReportFor('show analyst panel', ['analyst_panel.json'], {}).file, 'analyst_panel.json')
  assert.deepEqual(savedReportFor('show pricing', ['summary.json'], {marketing:{pricing:{optimal:3}}}).path, ['marketing','pricing'])
  assert.equal(savedReportFor('show pricing', [], {}), null)
})

test('connected reports and browser observations remain available to follow-up questions', () => {
  const context = buildConversationContext([{ role:'assistant', browser_observations:[{url:'https://example.com',text:'Pricing is shown on the page.'}], tool_results:[{connector:'Ads account',tool:'campaign_report',result:'{"clicks":12}'}] }])
  assert.equal(context.files.length, 2)
  assert.ok(context.text.includes('Pricing is shown'))
  assert.ok(context.text.includes('"clicks":12'))
})
