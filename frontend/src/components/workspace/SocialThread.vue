<script setup>
import { computed, ref } from 'vue'
import { MessageSquare, ThumbsUp, ThumbsDown } from 'lucide-vue-next'
import WorkspacePager from './WorkspacePager.vue'

const props = defineProps({ post: { type: Object, required: true }, sentimentMethod: { type: String, default: '' } })
const page = ref(0)
const replyCount = 10
const replies = computed(() => props.post.comments.slice(page.value * replyCount, (page.value + 1) * replyCount))
const fmt = value => new Intl.NumberFormat().format(value)
const sentiments = [['pos', 'Positive'], ['neu', 'Neutral'], ['neg', 'Negative']]
const replyScores = computed(() => sentiments
  .map(([id, label]) => ({ id, label, count: props.post.replySentiment?.[id] }))
  .filter(row => Number.isFinite(row.count) && row.count >= 0))
const sentimentTotal = computed(() => replyScores.value.reduce((total, row) => total + row.count, 0))
</script>

<template>
  <article class="social-thread">
    <header>
      <strong>{{ post.who }}</strong>
      <span>{{ post.platform }}<template v-if="post.round != null"> · Round {{ post.round }}</template></span>
    </header>
    <p v-if="post.segment || post.country" class="thread-subtitle">{{ [post.segment, post.country].filter(Boolean).join(' · ') }}</p>
    <blockquote v-if="post.quote">{{ post.quote }}</blockquote>
    <p v-if="post.text" class="thread-message">{{ post.text }}</p>
    <dl class="thread-counts">
      <div v-if="Number.isFinite(post.likes)"><dt><ThumbsUp :size="14" aria-hidden="true" /> Likes</dt><dd>{{ fmt(post.likes) }}</dd></div>
      <div v-if="Number.isFinite(post.dislikes)"><dt><ThumbsDown :size="14" aria-hidden="true" /> Dislikes</dt><dd>{{ fmt(post.dislikes) }}</dd></div>
      <div><dt><MessageSquare :size="14" aria-hidden="true" /> Saved replies</dt><dd>{{ fmt(post.comments.length) }}</dd></div>
    </dl>
    <figure v-if="sentimentTotal" class="thread-sentiment">
      <figcaption>Recorded reply sentiment<template v-if="sentimentMethod === 'lexicon'"> · word-based estimate</template></figcaption>
      <div class="sentiment-bar" aria-hidden="true"><span v-for="row in replyScores" :key="row.id" :class="row.id" :style="{ flexGrow: row.count }"></span></div>
      <ul><li v-for="row in replyScores" :key="row.id"><i :class="row.id" aria-hidden="true"></i>{{ row.label }} {{ fmt(row.count) }}</li></ul>
    </figure>
    <details v-if="post.comments.length" class="thread-replies">
      <summary>Read {{ fmt(post.comments.length) }} replies</summary>
      <ol>
        <li v-for="(reply, index) in replies" :key="reply.comment_id ?? index">
          <strong>{{ reply.author?.name || reply.name || (reply.user_id != null ? `Agent ${reply.user_id}` : 'Simulated participant') }}</strong>
          <small v-if="reply.author?.segment || reply.author?.country">{{ [reply.author?.segment, reply.author?.country].filter(Boolean).join(' · ') }}</small>
          <p>{{ reply.content || reply.text }}</p>
        </li>
      </ol>
      <WorkspacePager v-if="post.comments.length > replyCount" v-model:page="page" :size="replyCount" :total="post.comments.length" label="replies" />
    </details>
  </article>
</template>

<style scoped>
.social-thread { padding: 14px; border: 1px solid var(--line); border-radius: 12px; min-width: 0; }
.social-thread header { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 4px; font-size: 13px; }
.social-thread header > span, .thread-subtitle, .thread-sentiment, .thread-counts { color: var(--muted); font-size: 12px; }
.thread-subtitle { margin-top: 4px; }
.thread-message, .thread-replies p { margin: 7px 0 0; font-size: 13px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
.social-thread blockquote { padding: 6px 10px; margin: 8px 0 0; border-inline-start: 2px solid var(--line); font-size: 12px; overflow-wrap: anywhere; }
.thread-counts { display: flex; gap: 5px 13px; flex-wrap: wrap; margin: 11px 0 0; }
.thread-counts div, .thread-counts dt { display: inline-flex; align-items: center; gap: 5px; }
.thread-counts dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; }
.thread-sentiment { margin: 12px 0 0; }
.sentiment-bar { display: flex; margin: 5px 0; height: 6px; border-radius: 4px; overflow: hidden; }
.thread-sentiment ul { display: flex; flex-wrap: wrap; list-style: none; margin: 5px 0 0; padding: 0; gap: 3px 12px; }
.thread-sentiment li { display: inline-flex; align-items: center; gap: 5px; }
.thread-sentiment i { width: 7px; height: 7px; border-radius: 50%; }
.pos { background: var(--accent); } .neu { background: #92978e; } .neg { background: var(--no); }
.thread-replies { margin-top: 12px; padding-top: 9px; border-top: 1px solid var(--line); font-size: 12px; }
.thread-replies summary { cursor: pointer; width: fit-content; font-weight: 550; }
.thread-replies ol { list-style: none; padding-left: 10px; margin: 6px 0 0; }
.thread-replies li { border-inline-start: 2px solid var(--line); padding: 8px 0 8px 10px; }
.thread-replies small { display: block; color: var(--muted); margin-top: 3px; }
</style>
