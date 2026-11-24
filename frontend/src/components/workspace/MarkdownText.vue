<template><div class="chat-markdown" v-html="safeHtml"></div></template>
<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
const props = defineProps({ text: { type: String, default: '' } })
const safeHtml = computed(() => DOMPurify.sanitize(marked.parse(props.text, { breaks: true, gfm: true }), { FORBID_TAGS: ['style', 'iframe', 'form', 'input', 'button', 'svg', 'img'], FORBID_ATTR: ['style'] }))
</script>
<style scoped>
.chat-markdown{overflow-wrap:anywhere;line-height:1.8}.chat-markdown :deep(p+p){margin-top:12px}.chat-markdown :deep(h1),.chat-markdown :deep(h2),.chat-markdown :deep(h3){font-size:1.1em;font-weight:600;margin:18px 0 8px}.chat-markdown :deep(ul),.chat-markdown :deep(ol){padding-left:22px;margin:10px 0;list-style:revert}.chat-markdown :deep(li+li){margin-top:5px}.chat-markdown :deep(pre){background:var(--panel-2);padding:14px;border:1px solid var(--line);border-radius:8px;white-space:pre-wrap;margin:12px 0}.chat-markdown :deep(code){font-size:.9em;background:var(--panel-2);padding:2px 4px;border-radius:4px}.chat-markdown :deep(a){text-decoration:underline;color:var(--accent)}.chat-markdown :deep(table){display:block;overflow:auto;border-collapse:collapse;margin:12px 0}.chat-markdown :deep(th),.chat-markdown :deep(td){padding:8px 12px;border-bottom:1px solid var(--line);text-align:left}.chat-markdown :deep(blockquote){padding-left:14px;border-left:3px solid var(--line);color:var(--muted);margin:12px 0}
</style>
