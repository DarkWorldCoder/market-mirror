<template><span class="brand-icon" :style="style" aria-hidden="true"><img v-if="source" :src="source" alt="" :width="size" :height="size" /><span v-else>{{ brand.slice(0,1).toUpperCase() }}</span></span></template>
<script setup>
import { computed } from 'vue'
const props=defineProps({brand:{type:String,required:true},size:{type:Number,default:22}})
const sources=import.meta.glob('../assets/brands/*.svg',{eager:true,query:'?url',import:'default'})
const aliases={ga4:'googleanalytics',analytics:'googleanalytics',gemini:'googlegemini',claude:'anthropic',ads:'googleads',meta_ads:'meta',google_ads:'googleads',google_analytics:'googleanalytics'}
const id=computed(()=>aliases[props.brand]||props.brand)
const source=computed(()=>sources[`../assets/brands/${id.value}.svg`])
const style=computed(()=>({width:`${props.size}px`,height:`${props.size}px`}))
</script>
<style scoped>.brand-icon{display:inline-flex;align-items:center;justify-content:center;flex-shrink:0}.brand-icon img{width:100%;height:100%;object-fit:contain}.brand-icon span{font-size:15px;font-weight:650}[data-theme=dark] .brand-icon img{filter:invert(1)}</style>
