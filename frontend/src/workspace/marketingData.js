const normalize = value => String(value).toLowerCase().replace(/[^a-z0-9]/g,'')
const aliases = {
 impressions:['impressions','impression_count'], clicks:['clicks','link_clicks','inline_link_clicks','clicks_all'],
 spend:['spend','cost','amount_spent','ad_spend'], conversions:['conversions','purchases','website_purchases'],
 revenue:['revenue','purchase_conversion_value','purchases_conversion_value','website_purchases_conversion_value','purchase_value','conversion_value'],
}
const currencies = new Set(typeof Intl.supportedValuesOf==='function' ? Intl.supportedValuesOf('currency') : ['USD','EUR','GBP','NPR','INR','CAD','AUD','JPY','CNY','KES','PHP','SGD'])
const currencyCode = value => { const code=String(value||'').trim().toUpperCase();return currencies.has(code)?code:null }
const moneySymbols = {'€':'EUR','£':'GBP','₹':'INR','₩':'KRW','₽':'RUB','₫':'VND'}
const labelKeys = ['adname','creativename','adsetname','campaignname','name','label','country','accountname','title']
const identityKeys = ['adid','creativeid','adsetid','campaignid']
const totalLabels = new Set(['total','totals','grand total','account total','campaign total','results total','overall total'])
export const marketingMetrics = {impressions:'Impressions',clicks:'Clicks',spend:'Spend',conversions:'Recorded conversions',revenue:'Revenue',ctr:'CTR',cpc:'CPC',cpm:'CPM',cpa:'CPA',roas:'ROAS'}
export function marketingNumber(value) {
 if(typeof value==='number')return Number.isFinite(value)?value:null
 if(typeof value!=='string')return null
 let text=value.trim();if(!text || /%/.test(text))return null
 const negative=/^\(.*\)$/.test(text);if(negative)text=text.slice(1,-1)
 text=text.replace(/^[A-Z]{3}\s*/i,'').replace(/\s*[A-Z]{3}$/i,'').replace(/[$€£¥₹₩₽₫]/g,'').trim()
 if(/^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$/.test(text))text=text.replaceAll(',','')
 else if(/^-?\d{1,3}(?:[ \u00a0]\d{3})+(?:\.\d+)?$/.test(text))text=text.replace(/[ \u00a0]/g,'')
 if(!/^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text))return null
 const number=Number(text)*(negative?-1:1);return Number.isFinite(number)?number:null
}
function field(row,names) {
 const entries=Object.entries(row)
 for(const name of names) {
  const match=entries.find(([key])=>{let base=key;const suffix=key.match(/(?:\(|\[|_|\s)([A-Z]{3})(?:\)|\])?$/i);if(suffix&&currencyCode(suffix[1]))base=key.slice(0,suffix.index);return normalize(base)===normalize(name)})
  if(match)return {key:match[0],value:match[1]}
 }
 return null
}
function moneyCurrency(item,declared) {
 if(!item)return null
 const hints=[]
 const suffix=item.key.match(/(?:\(|\[|_|\s)([A-Z]{3})(?:\)|\])?$/i);if(suffix&&currencyCode(suffix[1]))hints.push(currencyCode(suffix[1]))
 if(declared)hints.push(declared)
 if(typeof item.value==='string') {
  const code=item.value.match(/(?:^|\s)([A-Z]{3})(?:\s|$)/i);if(code&&currencyCode(code[1]))hints.push(currencyCode(code[1]))
  for(const [symbol,currency] of Object.entries(moneySymbols))if(item.value.includes(symbol))hints.push(currency)
 }
 return hints.length && new Set(hints).size===1 ? hints[0] : null
}
const ratio=(numerator,denominator,multiplier=1)=>Number.isFinite(numerator)&&Number.isFinite(denominator)&&denominator>0?numerator/denominator*multiplier:null
function derive(base,currency,spendCurrency=currency,revenueCurrency=currency) {
 return {...base,ctr:ratio(base.clicks,base.impressions,100),cpc:spendCurrency?ratio(base.spend,base.clicks):null,cpm:spendCurrency?ratio(base.spend,base.impressions,1000):null,cpa:spendCurrency?ratio(base.spend,base.conversions):null,roas:spendCurrency&&spendCurrency===revenueCurrency?ratio(base.revenue,base.spend):null}
}
function dateValue(value) {const text=String(value||'').slice(0,10);if(!/^\d{4}-\d{2}-\d{2}$/.test(text))return null;const time=Date.parse(text+'T00:00:00Z');return Number.isFinite(time)&&new Date(time).toISOString().slice(0,10)===text?text:null}
function rowsFrom(data) {
 const candidates=[data,data?.rows,data?.data,data?.results,data?.records,data?.structuredContent?.rows,data?.structuredContent?.data,data?.data?.rows]
 for(const value of candidates)if(Array.isArray(value)&&value.length&&value.every(row=>row&&typeof row==='object'&&!Array.isArray(row)))return value
 return data&&typeof data==='object'&&!Array.isArray(data)&&Object.values(aliases).some(names=>field(data,names))?[data]:[]
}
export function analyzeMarketingData(data) {
 const source=rowsFrom(data);if(!source.length)return null
 const metadataCurrencies=[data?.currency,data?.currency_code,data?.data?.currency,data?.data?.currency_code,data?.structuredContent?.currency,data?.structuredContent?.currency_code].map(currencyCode).filter(Boolean)
 const defaultCurrency=new Set(metadataCurrencies).size===1?metadataCurrencies[0]:null
 const allRows=source.map((raw,index)=>{
  const entries=Object.fromEntries(Object.entries(raw).map(([key,value])=>[normalize(key),value]))
  const fields=Object.fromEntries(Object.entries(aliases).map(([metric,names])=>[metric,field(raw,names)]))
  const base=Object.fromEntries(Object.entries(fields).map(([metric,item])=>[metric,marketingNumber(item?.value)]))
  for(const key of ['impressions','clicks','conversions'])if(base[key]!==null&&base[key]<0)base[key]=null
  const declared=currencyCode(entries.currency || entries.accountcurrency || entries.currencycode) || defaultCurrency
  const spendCurrency=moneyCurrency(fields.spend,currencyCode(entries.spendcurrency || entries.costcurrency)||declared)
  const revenueCurrency=moneyCurrency(fields.revenue,currencyCode(entries.revenuecurrency)||declared)
  const mixedCurrency=base.spend!==null&&base.revenue!==null&&spendCurrency&&revenueCurrency&&spendCurrency!==revenueCurrency
  const currency=mixedCurrency?null:base.spend!==null?spendCurrency:revenueCurrency
  const labelKey=labelKeys.find(key=>entries[key]!==undefined&&String(entries[key]).trim())
  const label=labelKey?String(entries[labelKey]).trim():`Row ${index+1}`
  const dateKey=['date','day','datestart','reportingstarts'].find(key=>entries[key]!==undefined)
  const date=dateValue(entries[dateKey]),endDate=dateValue(entries.datestop || entries.dateend || entries.reportingends)
  const identities=Object.fromEntries(identityKeys.filter(key=>entries[key]!==undefined&&String(entries[key]).trim()&&!['--','—','n/a','null','none','all','(not set)'].includes(String(entries[key]).trim().toLowerCase())&&!totalLabels.has(String(entries[key]).trim().toLowerCase())).map(key=>[key,String(entries[key])]))
  return {raw,index,label,labelField:labelKey,date,daily:dateKey==='date'||dateKey==='day'||date&&endDate===date,currency,spendCurrency,revenueCurrency,mixedCurrency,total:!Object.keys(identities).length&&labelKeys.some(key=>totalLabels.has(String(entries[key]||'').trim().toLowerCase())),identities,metrics:derive(base,currency,spendCurrency,revenueCurrency),fields}
 })
 if(!allRows.some(row=>Object.values(row.fields).filter(Boolean).length>=2&&Object.values(row.metrics).some(Number.isFinite)))return null
 const details=allRows.filter(row=>!row.total),rows=details.length?details:allRows,excludedTotalRows=details.length?allRows.filter(row=>row.total):[]
 const grouped=new Map()
 for(const row of rows){const key=row.mixedCurrency?'mixed':row.currency||'unknown';if(!grouped.has(key))grouped.set(key,[]);grouped.get(key).push(row)}
 const groups=[...grouped.entries()].map(([key,items])=>{
  const currency=key!=='mixed'&&key!=='unknown'?key:null
  const identity=identityKeys.find(field=>items.every(row=>row.identities[field]))
  const keys=identity?items.map(row=>row.identities[identity]+(row.daily&&row.date?'@'+row.date:'')):[]
  const canAggregate=items.length===1||Boolean(identity&&new Set(keys).size===items.length)
  let aggregate=null
  if(canAggregate){const base={};for(const metric of Object.keys(aliases))base[metric]=items.every(row=>Number.isFinite(row.metrics[metric]))?items.reduce((sum,row)=>sum+row.metrics[metric],0):null
   if(!currency || !items.every(row=>row.spendCurrency===currency))base.spend=null
   if(!currency || !items.every(row=>row.revenueCurrency===currency))base.revenue=null
   aggregate=derive(base,currency)
   if(items.length===1)aggregate=items[0].metrics
  }
  const comparable=items.filter(row=>currency&&row.spendCurrency===currency&&row.revenueCurrency===currency&&row.metrics.roas!==null)
  const bestRoas=comparable.length>1?[...comparable].sort((a,b)=>b.metrics.roas-a.metrics.roas)[0]:null
  return {key,currency,label:currency|| (key==='mixed'?'Mixed spend/revenue currencies':'Currency not supplied'),rows:items,aggregate,bestRoas,aggregationNote:canAggregate?'':'Combined totals are withheld because these rows may overlap.'}
 })
 return {rows,allRows,groups,excludedTotalRows,multipleCurrencies:groups.length>1}
}
