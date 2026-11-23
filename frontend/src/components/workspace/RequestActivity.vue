<script setup>
import { computed } from 'vue'
import { Check, ChevronDown, CircleAlert, LoaderCircle } from 'lucide-vue-next'
const props=defineProps({events:{type:Array,default:()=>[]},busy:Boolean,mode:{default:'standard'}})
const steps=computed(()=>{
 const result=[]
 for(const event of props.events){
  const key=[event.type,event.id || event.tool || '',event.turn || ''].join(':')
  const index=result.findIndex(item=>item.key===key)
  const item={...event,key}
  if(index<0)result.push(item);else result[index]=item
 }
 return result
})
const working=computed(()=>steps.value.filter(event=>event.status==='working'))
const current=computed(()=>working.value.at(-1)?.label || (props.mode==='note'?'Sharing your note…':props.busy?'Preparing your answer…':'Request activity'))
</script>
<template>
 <details class="request-activity">
  <summary><LoaderCircle v-if="busy" class="activity-spin" :size="14" /><Check v-else :size="14" /><span>{{ current }}</span><small v-if="steps.length">{{ steps.length }} {{ steps.length===1?'step':'steps' }}</small><ChevronDown :size="13" class="activity-chevron" /></summary>
  <ol v-if="steps.length"><li v-for="event in steps" :key="event.key"><Check v-if="event.status==='completed'" :size="13" /><CircleAlert v-else-if="event.status==='failed'" :size="13" /><LoaderCircle v-else :size="13" class="activity-spin" /><div><span>{{ event.label || event.role || event.tool }}</span><small v-if="event.model">{{ event.model }}</small><p v-if="event.summary">{{ event.summary }}</p></div></li></ol>
  <p v-else class="activity-empty">Waiting for the server. Tool calls and reviewer updates appear here as they arrive.</p>
 </details>
</template>
<style scoped>
.request-activity{border:1px solid var(--line);border-radius:12px;background:var(--panel);font-size:12px;color:var(--muted);overflow:hidden}.request-activity summary{display:flex;align-items:center;gap:9px;padding:12px 14px;cursor:pointer;list-style:none}.request-activity summary::-webkit-details-marker{display:none}.request-activity summary>span{flex:1;color:var(--text);min-width:0;overflow-wrap:anywhere}.request-activity summary>small{font-size:11px;white-space:nowrap}.activity-chevron{transition:transform .15s}.request-activity[open] .activity-chevron{transform:rotate(180deg)}.request-activity ol{list-style:none;margin:0;padding:4px 14px 14px;display:grid;gap:12px;border-top:1px solid var(--line)}.request-activity li{display:flex;gap:9px;align-items:flex-start;padding-top:10px;line-height:1.6}.request-activity li>svg{flex-shrink:0;margin-top:3px}.request-activity li div{min-width:0}.request-activity li small{display:block;font-size:11px}.request-activity li p{margin:5px 0 0;white-space:pre-wrap}.activity-empty{padding:0 14px 14px;font-size:12px;line-height:1.6}.activity-spin{animation:activity-spin 1s linear infinite}@keyframes activity-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.activity-spin{animation:none}}
</style>
