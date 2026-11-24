<template><details class="connected-result" open><summary><Plug :size="15" /><span>{{ result.connector }} · {{ result.tool.replaceAll('_',' ') }}</span></summary><p v-if="result.truncated" class="connected-result-note">This response was shortened by the connector limit.</p><MarketingDataCard v-if="marketing" :data="data" :theme="theme" /><ResultTree v-else :value="data" :theme="theme" /></details></template>
<script setup>
import { computed } from 'vue'
import { Plug } from 'lucide-vue-next'
import ResultTree from './ResultTree.vue'
import MarketingDataCard from './MarketingDataCard.vue'
import { analyzeMarketingData } from '../../workspace/marketingData.js'
const props=defineProps({result:{type:Object,required:true},theme:{default:'light'}})
const data=computed(()=>{let value;try{value=JSON.parse(props.result.result)}catch{return props.result.result}if(value.structuredContent)return value.structuredContent;const content=value.content;if(Array.isArray(content)&&content.every(c=>c.type==='text'))return content.map(c=>{try{return JSON.parse(c.text)}catch{return c.text}}).length===1?(()=>{try{return JSON.parse(content[0].text)}catch{return content[0].text}})():content.map(c=>c.text);return value})
const marketing=computed(()=>!!analyzeMarketingData(data.value))
</script>
<style scoped>.connected-result{margin-top:16px;padding:16px;background:var(--panel);border:1px solid var(--line);border-radius:12px;min-width:0}.connected-result summary{display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;margin-bottom:12px}.connected-result-note{font-size:12px;color:var(--muted);margin-bottom:12px}</style>
