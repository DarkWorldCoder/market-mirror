<template>
  <article class="pp" :class="[layout, { brand: post.isBrand }]" :aria-label="`${styleLabel} post by ${post.who}, simulated`">
    <!-- Reddit-style: vote column on the left -->
    <div v-if="layout === 'forum'" class="pp-votes" aria-label="Score">
      <ArrowBigUp :size="18" aria-hidden="true" /><b>{{ fmt(score) }}</b><ArrowBigDown :size="18" aria-hidden="true" />
    </div>

    <div class="pp-main">
      <header class="pp-head">
        <span v-if="layout === 'feed'" class="pp-avatar" :style="{ background: color }" aria-hidden="true">{{ initials }}</span>
        <div class="pp-who">
          <template v-if="layout === 'feed'">
            <b>{{ post.who }}</b>
            <span class="pp-handle">{{ handle }}</span>
          </template>
          <template v-else>
            <span class="pp-community">{{ community }}</span>
            <span class="pp-handle">Posted by {{ post.who }}</span>
          </template>
          <span class="pp-meta">{{ meta }}</span>
        </div>
        <span class="pp-tags">
          <span v-if="post.isBrand" class="pp-tag brand">Brand</span>
          <span class="pp-tag">{{ styleLabel }}</span>
          <span class="pp-tag sim">Simulated</span>
        </span>
      </header>

      <p v-if="post.kind === 'repost' && post.original" class="pp-reposted"><Repeat2 :size="13" aria-hidden="true" />Shared a post by {{ post.original.who }}</p>
      <h4 v-if="layout === 'forum' && title" class="pp-title">{{ title }}</h4>
      <p v-if="body" class="pp-text">{{ body }}</p>
      <blockquote v-if="post.quote && post.kind !== 'quote'" class="pp-quote">{{ post.quote }}</blockquote>
      <div v-if="post.kind === 'quote' && post.original" class="pp-quote-card">
        <small>Quoting {{ post.original.who }}</small>
        <p v-if="post.quote">{{ post.quote }}</p>
      </div>

      <footer class="pp-actions">
        <span :aria-label="`${post.comments.length} replies`"><MessageCircle :size="15" aria-hidden="true" />{{ fmt(post.comments.length) }}</span>
        <span v-if="layout === 'feed'" role="img" :aria-label="`${fmt(shares)} ${shares === 1 ? 'share' : 'shares'}`"><Repeat2 :size="15" aria-hidden="true" />{{ fmt(shares) }}</span>
        <span v-if="layout === 'feed'" :aria-label="`${post.likes ?? 0} likes`"><Heart :size="15" aria-hidden="true" />{{ fmt(post.likes || 0) }}</span>
        <span v-if="Number.isFinite(post.dislikes) && post.dislikes > 0" :aria-label="`${post.dislikes} dislikes`"><ThumbsDown :size="15" aria-hidden="true" />{{ fmt(post.dislikes) }}</span>
        <span v-if="sentimentText" class="pp-sentiment">{{ sentimentText }}</span>
      </footer>

      <ol v-if="shownReplies.length" class="pp-replies" :class="layout">
        <li v-for="(r, i) in shownReplies" :key="r.comment_id ?? i">
          <span v-if="layout === 'feed'" class="pp-avatar sm" :style="{ background: colorFor(r.author?.segment) }" aria-hidden="true">{{ initialsFor(replyName(r)) }}</span>
          <div>
            <p class="pp-reply-head"><b>{{ replyName(r) }}</b><span>{{ [r.author?.segment, r.author?.country, r.round != null ? `round ${r.round}` : ''].filter(Boolean).join(' · ') }}</span></p>
            <p class="pp-reply-text">{{ r.content || r.text }}</p>
            <p v-if="Number.isFinite(r.likes) && r.likes > 0" class="pp-reply-likes"><component :is="layout === 'forum' ? ArrowBigUp : Heart" :size="12" aria-hidden="true" />{{ fmt(r.likes) }}</p>
          </div>
        </li>
      </ol>
      <button v-if="post.comments.length > shownReplies.length" type="button" class="pp-more" @click="limit += 10">
        Show {{ Math.min(10, post.comments.length - shownReplies.length) }} more {{ post.comments.length - shownReplies.length === 1 ? 'reply' : 'replies' }}
      </button>
    </div>
  </article>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ArrowBigDown, ArrowBigUp, Heart, MessageCircle, Repeat2, ThumbsDown } from 'lucide-vue-next'
import { platformStyle } from '../../workspace/socialPosts'

const props = defineProps({ post: { type: Object, required: true }, sentimentMethod: { type: String, default: '' } })
const limit = ref(2)
const PALETTE = ['#25785d', '#507cba', '#a76a40', '#9568aa', '#ab8834', '#278d99', '#b0606b', '#5e7f40']
const hash = (v) => [...String(v || '')].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7)
const colorFor = (seg) => PALETTE[hash(seg) % PALETTE.length]
const initialsFor = (name) => String(name || '?').split(/\s+/).map((w) => w[0]).filter(Boolean).slice(0, 2).join('').toUpperCase()
const fmt = (v) => new Intl.NumberFormat().format(v || 0)

const layout = computed(() => (String(props.post.platform).toLowerCase() === 'reddit' ? 'forum' : 'feed'))
const styleLabel = computed(() => platformStyle(props.post.platform))
const color = computed(() => (props.post.isBrand ? '#1f6b4f' : colorFor(props.post.segment)))
const initials = computed(() => initialsFor(props.post.who))
const handle = computed(() => (props.post.isBrand ? 'Brand account' : [props.post.segment, props.post.country].filter(Boolean).join(' · ') || 'Simulated person'))
const community = computed(() => (props.post.segment ? `Community · ${props.post.segment}` : props.post.isBrand ? 'Brand post' : 'Community'))
const meta = computed(() => [props.post.round != null ? `Round ${props.post.round}` : '', props.post.hour || ''].filter(Boolean).join(' · '))
const score = computed(() => props.post.score ?? ((props.post.likes || 0) - (props.post.dislikes || 0)))
const shares = computed(() => (props.post.reposts ?? 0) + (props.post.quoteCount ?? 0))
// forum posts read like a title and a body: first sentence as the title
const split = computed(() => {
  const t = String(props.post.text || '').trim()
  if (layout.value !== 'forum' || t.length < 90) return { title: layout.value === 'forum' ? t : '', body: layout.value === 'forum' ? '' : t }
  const m = t.match(/^(.{20,140}?[.!?])\s+(.*)$/s)
  return m ? { title: m[1], body: m[2] } : { title: t.slice(0, 120) + (t.length > 120 ? '…' : ''), body: t.length > 120 ? t : '' }
})
const title = computed(() => split.value.title)
const body = computed(() => (layout.value === 'forum' ? split.value.body : props.post.text))
const replyName = (r) => r.author?.name || r.name || (r.user_id != null ? `Person ${r.user_id}` : 'Simulated person')
const shownReplies = computed(() => props.post.comments.slice(0, limit.value))
const sentimentText = computed(() => {
  const s = props.post.replySentiment
  if (!s) return ''
  const total = (s.pos || 0) + (s.neu || 0) + (s.neg || 0)
  if (!total) return ''
  return `Replies: ${s.pos || 0} positive · ${s.neu || 0} neutral · ${s.neg || 0} negative${props.sentimentMethod === 'lexicon' ? ' (word-based estimate)' : ''}`
})
</script>

<style scoped>
.pp { display: flex; gap: 10px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 14px; background: var(--panel); min-width: 0; }
.pp.brand { border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); background: color-mix(in srgb, var(--accent) 5%, var(--panel)); box-shadow: inset 3px 0 0 var(--accent); }
.pp-main { flex: 1; min-width: 0; }
.pp-head { display: flex; align-items: flex-start; gap: 10px; min-width: 0; }
.pp-avatar { width: 38px; height: 38px; flex: none; border-radius: 50%; display: grid; place-items: center; color: #fff; font-size: 13px; font-weight: 650; }
.pp-avatar.sm { width: 26px; height: 26px; font-size: 10.5px; }
.pp-who { flex: 1; min-width: 0; display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 8px; font-size: 13px; line-height: 1.4; }
.pp-who b { font-weight: 650; }
.pp-handle, .pp-meta { color: var(--muted); font-size: 12px; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.pp-community { font-weight: 650; font-size: 12.5px; }
.pp-meta::before { content: '· '; }
.pp-tags { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px; flex: none; max-width: 45%; }
.pp-tag { font-size: 10.5px; border: 1px solid var(--line); border-radius: 999px; padding: 0 7px; color: var(--muted); white-space: nowrap; }
.pp-tag.sim { color: var(--warm); border-color: color-mix(in srgb, var(--warm) 45%, var(--line)); }
.pp-tag.brand { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); }
.pp-reposted { display: flex; align-items: center; gap: 5px; margin: 8px 0 0; font-size: 12px; color: var(--muted); }
.pp-title { margin: 8px 0 0; font-size: 15px; font-weight: 650; line-height: 1.4; overflow-wrap: anywhere; }
.pp-text { margin: 8px 0 0; font-size: 14px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
.pp.feed .pp-text, .pp.feed .pp-reposted, .pp.feed .pp-quote, .pp.feed .pp-quote-card, .pp.feed .pp-actions, .pp.feed .pp-replies, .pp.feed .pp-more { margin-left: 48px; }
.pp-quote { margin: 8px 0 0; padding: 6px 10px; border-left: 3px solid var(--line); color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
.pp-quote-card { margin-top: 10px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel-2); font-size: 13px; }
.pp-quote-card small { color: var(--muted); font-size: 11.5px; }
.pp-quote-card p { margin: 4px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.pp-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 18px; margin-top: 10px; color: var(--muted); font-size: 12.5px; font-variant-numeric: tabular-nums; }
.pp-actions > span { display: inline-flex; align-items: center; gap: 5px; }
.pp-sentiment { font-size: 11.5px; }
.pp-votes { display: flex; flex-direction: column; align-items: center; gap: 2px; width: 34px; flex: none; color: var(--muted); font-size: 12.5px; }
.pp-votes b { color: var(--text); font-variant-numeric: tabular-nums; }
.pp-replies { list-style: none; margin: 12px 0 0; padding: 0; display: grid; gap: 10px; }
.pp-replies li { display: flex; gap: 8px; min-width: 0; }
.pp-replies.forum li { padding-left: 12px; border-left: 2px solid var(--line); }
.pp-replies li > div { min-width: 0; }
.pp-reply-head { display: flex; flex-wrap: wrap; gap: 2px 8px; margin: 0; font-size: 12.5px; }
.pp-reply-head span { color: var(--muted); font-size: 11.5px; }
.pp-reply-text { margin: 2px 0 0; font-size: 13px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; }
.pp-reply-likes { display: inline-flex; align-items: center; gap: 3px; margin: 3px 0 0; font-size: 11.5px; color: var(--muted); }
.pp-more { margin-top: 8px; border: 0; background: none; padding: 4px 0; color: var(--accent); font-size: 12.5px; cursor: pointer; }
.pp-more:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
@media (max-width: 600px) {
  .pp { padding: 12px; }
  .pp-head { flex-wrap: wrap; }
  .pp-tags { max-width: 100%; justify-content: flex-start; order: 3; width: 100%; padding-left: 48px; }
  .pp.forum .pp-tags { padding-left: 0; }
  .pp.feed .pp-text, .pp.feed .pp-reposted, .pp.feed .pp-quote, .pp.feed .pp-quote-card, .pp.feed .pp-actions, .pp.feed .pp-replies, .pp.feed .pp-more { margin-left: 0; }
}
</style>
