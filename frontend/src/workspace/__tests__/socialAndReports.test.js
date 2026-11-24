import test from 'node:test'
import assert from 'node:assert/strict'
import { feedAds, platformStyle, socialPosts } from '../socialPosts.js'
import { presentReport, technicalKey } from '../reportPresentation.js'

test('platform labels are layout names, not branding', () => {
  assert.equal(platformStyle('twitter'), 'Twitter-style')
  assert.equal(platformStyle('reddit'), 'Reddit-style')
  assert.equal(platformStyle('linkedin'), 'LinkedIn-style')
  assert.equal(platformStyle(''), 'Feed')
})
test('posts carry kind, brand flag and original author for platform cards', () => {
  const story = { platforms: { twitter: { posts: [
    { post_id: 1, kind: 'post', is_brand: true, author: { name: 'Fitloop', kind: 'graph' }, content: 'Launch', reposts: 2, quotes: [4, 6] },
    { post_id: 4, kind: 'quote', author: { name: 'Grace', kind: 'persona', agent_id: 3 }, quote_content: 'Nice', original: { author: { name: 'Fitloop' }, post_id: 1 } }
  ] } } }
  const [brand, quote] = socialPosts(story)
  assert.equal(brand.isBrand, true)
  assert.equal(brand.quoteCount, 2)
  assert.equal(quote.kind, 'quote')
  assert.equal(quote.original.who, 'Fitloop')
})
test('feed ads count what people did, from the first seed only', () => {
  const ads = feedAds({ seed: 1, creatives: [{ id: 'a', name: 'Ad A', platform: 'instagram' }], sessions: [
    { seed: 1, creative_id: 'a', name: 'Ana', ad: { click: true, thought: 'Want it' } },
    { seed: 1, creative_id: 'a', ad: { hide: true } },
    { seed: 1, creative_id: 'a', ad: { stopped: true } },
    { seed: 1, creative_id: 'a', ad: {} },
    { seed: 2, creative_id: 'a', ad: { click: true } }
  ] })
  assert.deepEqual([ads[0].shown, ads[0].clicked, ads[0].hid, ads[0].stopped, ads[0].scrolled], [4, 1, 1, 1, 1])
  assert.equal(ads[0].thoughts[0].did, 'Clicked')
})
test('analyst panel reads as verdict, analyst cards and themes; plumbing stays technical', () => {
  const r = presentReport('analyst_panel.json', { brief: 'Launch?', analysts: [{ id: 'A', lens: 'Marketer', result: { headline: 'Fix trust first', confidence: 6 } }],
    consensus: { verdict: { winner: 'iterate', agreement: 100, votes: { iterate: 1 } }, success_probability: 31, themes: [{ theme: 'Trust', share: 60 }] }, material_counts: { posts: 3 } })
  assert.equal(r.cards.find((c) => c.label === 'Verdict').value, 'Iterate')
  assert.ok(r.sections.some((s) => s.type === 'cards' && s.items[0].title === 'Marketer'))
  assert.ok(!JSON.stringify(r).includes('material_counts'))
  assert.equal(technicalKey('material_counts'), true)
  assert.equal(technicalKey('consensus'), false)
})
test('unknown files fall back to the generic view', () => {
  assert.equal(presentReport('future.json', { a: 1 }), null)
})
