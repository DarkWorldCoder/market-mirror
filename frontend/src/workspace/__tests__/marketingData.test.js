import test from 'node:test'
import assert from 'node:assert/strict'
import { analyzeMarketingData as analyze, marketingNumber } from '../marketingData.js'

test('actual ad math uses matching source units and weighted totals, excludes explicit total rows visibly',()=>{
 const data=analyze([
  {ad_id:'a',ad_name:'Creative A',Impressions:'1,000',LINK_CLICKS:'50',Spend:'100',Purchases:'5',purchase_conversion_value:'300',Currency:'USD'},
  {ad_id:'b',ad_name:'Creative B',Impressions:1000,LINK_CLICKS:50,Spend:100,Purchases:5,purchase_conversion_value:100,Currency:'USD'},
  {ad_id:'--',ad_name:'Total',Impressions:2000,LINK_CLICKS:100,Spend:200,Purchases:10,purchase_conversion_value:400,Currency:'USD'},
 ])
 assert.equal(data.allRows.length,3);assert.equal(data.excludedTotalRows.length,1);assert.equal(data.rows.length,2)
 const a=data.rows[0].metrics
 assert.deepEqual([a.ctr,a.cpc,a.cpm,a.cpa,a.roas],[5,2,100,20,3])
 assert.equal(data.groups[0].aggregate.spend,200)
 assert.equal(data.groups[0].aggregate.roas,2)
 assert.equal(data.groups[0].bestRoas.label,'Creative A')
})
test('zero denominators and missing values remain unknown; zero spend ratios may be actual zero',()=>{
 const zero=analyze([{impressions:0,clicks:0,spend:0,conversions:0,revenue:0,currency:'USD'}]).rows[0].metrics
 for(const key of ['ctr','cpc','cpm','cpa','roas'])assert.equal(zero[key],null,key)
 const free=analyze([{impressions:100,clicks:10,spend:0,conversions:1,revenue:0,currency:'USD'}]).rows[0].metrics
 assert.deepEqual([free.ctr,free.cpc,free.cpm,free.cpa,free.roas],[10,0,0,0,null])
 const missing=analyze([{impressions:100,clicks:10,cost:30,purchases:'',currency:'USD'}]).rows[0].metrics
 assert.equal(missing.cpa,null);assert.equal(missing.revenue,null);assert.equal(missing.roas,null)
})
test('percent strings never become count numerators and unqualified dollar signs do not invent USD',()=>{
 const row=analyze([{impressions:'1000',clicks:'2%',spend:'$12'}]).rows[0]
 assert.equal(row.metrics.clicks,null);assert.equal(row.metrics.ctr,null)
 assert.equal(row.metrics.spend,12);assert.equal(row.spendCurrency,null);assert.equal(row.metrics.cpm,null)
 assert.equal(marketingNumber('1,200.50'),1200.5);assert.equal(marketingNumber('—'),null);assert.equal(marketingNumber('1,5'),null)
})
test('explicit field currencies can be parsed, but mismatched revenue never produces ROAS',()=>{
 const row=analyze([{'Spend (USD)':'$12','Revenue (EUR)':'€24',clicks:6,impressions:100}]).rows[0]
 assert.equal(row.spendCurrency,'USD');assert.equal(row.revenueCurrency,'EUR');assert.equal(row.mixedCurrency,true)
 assert.equal(row.metrics.cpc,2);assert.equal(row.metrics.roas,null)
})
test('different currencies return separate groups without a combined monetary total',()=>{
 const data=analyze([{ad_id:'a',spend:100,revenue:200,currency:'USD'},{ad_id:'b',spend:200,revenue:400,currency:'EUR'}])
 assert.equal(data.multipleCurrencies,true);assert.equal(data.groups.length,2)
 assert.deepEqual(data.groups.map(group=>[group.currency,group.aggregate.spend]),[['USD',100],['EUR',200]])
 assert.equal(data.aggregate,undefined)
})
test('ambiguous or overlapping rows are not added together and real entities named Total remain records',()=>{
 const data=analyze([{ad_id:'a',ad_name:'Total',spend:10,clicks:5,currency:'USD'},{ad_id:'a',ad_name:'Other',spend:20,clicks:10,currency:'USD'}])
 assert.equal(data.excludedTotalRows.length,0);assert.equal(data.groups[0].aggregate,null)
 assert.match(data.groups[0].aggregationNote,/may overlap/)
 const unnamed=analyze([{spend:10,clicks:5,currency:'USD'},{spend:20,clicks:10,currency:'USD'}])
 assert.equal(unnamed.groups[0].aggregate,null)
})
test('distinct daily records may aggregate, invalid dates do not create a false time axis',()=>{
 const daily=analyze([{ad_id:'a',date:'2026-01-01',clicks:10,impressions:100},{ad_id:'a',date:'2026-01-02',clicks:30,impressions:300}])
 assert.equal(daily.groups[0].aggregate.ctr,10)
 assert.equal(analyze([{date:'2026-02-30',clicks:10,impressions:100}]).rows[0].date,null)
})
test('structured row containers are supported and unrelated analytics or fuzzy names render nothing',()=>{
 assert.equal(analyze({structuredContent:{currency:'USD',rows:[{cost:10,revenue:20}]}}).rows[0].metrics.roas,2)
 assert.equal(analyze([{name:'Site',sessions:10,users:8}]),null)
 assert.equal(analyze([{impressions:10,clickbait:8}]),null)
})
