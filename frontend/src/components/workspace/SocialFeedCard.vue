<script setup>
import { computed, ref, watch } from 'vue'
import { Search } from 'lucide-vue-next'
import { api } from '../../workspace/api'
import { neededRawPosts, socialPosts } from '../../workspace/socialPosts'
import SocialThread from './SocialThread.vue'
import LoadingSkeleton from './LoadingSkeleton.vue'
import WorkspacePager from './WorkspacePager.vue'

const props = defineProps({ name: { type: String, required: true }, files: { type: Array, required: true } })
const story = ref(null), timeline = ref([]), raw = ref({})
const loading = ref(false), error = ref(''), partial = ref(false)
const query = ref(''), platform = ref(''), round = ref(''), sort = ref('recorded'), page = ref(0)
const size = 5
let ticket = 0

async function load() {
  const id = ++ticket
  const files = [...props.files]
  const base = `/api/runs/${encodeURIComponent(props.name)}/files/`
  const read = file => api(base + encodeURIComponent(file))
  loading.value = true
  error.value = ''
  partial.value = false
  try {
    const social = await Promise.allSettled([
      files.includes('feed_story.json') ? read('feed_story.json') : null,
      files.includes('timeline.json') ? read('timeline.json') : []
    ])
    const [feed, rounds] = social.map(result => result.status === 'fulfilled' ? result.value : null)
    const alternatives = await Promise.allSettled(neededRawPosts(feed, files).map(async source => {
      const repliesFile = `comments_${source}.json`
      const posts = await read(`posts_${source}.json`)
      const replies = files.includes(repliesFile) ? await read(repliesFile).catch(() => null) : []
      const byPost = new Map()
      for (const reply of Array.isArray(replies) ? replies : []) {
        const key = String(reply.post_id)
        if (!byPost.has(key)) byPost.set(key, [])
        byPost.get(key).push(reply)
      }
      const rows = Array.isArray(posts) ? posts : posts?.posts || []
      return [source, rows.map(post => ({
        ...post, comments: post.comments?.length ? post.comments : byPost.get(String(post.post_id ?? post.id)) || []
      })), replies === null]
    }))
    if (id !== ticket) return
    const available = alternatives.filter(result => result.status === 'fulfilled').map(result => result.value)
    const someUnavailable = [...social, ...alternatives].some(result => result.status === 'rejected') || available.some(row => row[2])
    story.value = feed
    timeline.value = Array.isArray(rounds) ? rounds : []
    raw.value = Object.fromEntries(available.map(([source, rows]) => [source, rows]))
    if (someUnavailable && !feed && !available.length && !timeline.value.length) error.value = 'Could not open the saved social activity. Try loading it again.'
    else partial.value = someUnavailable
  } finally {
    if (id === ticket) loading.value = false
  }
}
watch(() => [props.name, props.files], load, { immediate: true })
watch(() => props.name, () => { query.value = ''; platform.value = ''; round.value = ''; sort.value = 'recorded' })

const posts = computed(() => socialPosts(story.value, raw.value))
const platforms = computed(() => [...new Set(posts.value.map(post => post.platform))])
const rounds = computed(() => [...new Set(posts.value.map(post => post.round).filter(value => Number.isFinite(value)))].sort((a, b) => a - b))
const filtered = computed(() => {
  const term = query.value.trim().toLowerCase()
  const rows = posts.value.filter(post => {
    if (platform.value && post.platform !== platform.value) return false
    if (round.value !== '' && post.round !== round.value) return false
    return !term || [post.who, post.text, post.quote, post.country, post.segment].some(value => value?.toLowerCase().includes(term)) ||
      post.comments.some(reply => [reply.content, reply.text, reply.author?.name].some(value => value?.toLowerCase().includes(term)))
  })
  if (sort.value === 'replies') return rows.sort((a, b) => b.comments.length - a.comments.length)
  if (sort.value === 'likes') return rows.sort((a, b) => (b.likes ?? -1) - (a.likes ?? -1))
  return rows
})
watch([query, platform, round, sort, posts], () => { page.value = 0 })
const visible = computed(() => filtered.value.slice(page.value * size, (page.value + 1) * size))
const activity = computed(() => timeline.value
  .filter(row => Number.isFinite(row.round_num) && Number.isFinite(row.total_actions) && row.total_actions >= 0)
  .sort((a, b) => a.round_num - b.round_num))
const maximum = computed(() => Math.max(1, ...activity.value.map(row => row.total_actions)))
const fmt = value => new Intl.NumberFormat().format(value)
</script>

<template>
  <section class="social-feed-card" aria-label="Saved social feed">
    <LoadingSkeleton v-if="loading" :lines="5" label="Loading saved social activity" />
    <p v-else-if="error" role="alert">{{ error }} <button class="ws-btn" @click="load">Retry</button></p>
    <template v-else>
      <p>Posts and replies from the simulation.</p>
      <p v-if="partial" role="status">Some saved social sources could not load. <button class="ws-btn" @click="load">Retry</button></p>
      <section v-if="activity.length" class="social-rounds" aria-label="Actions by round">
        <h3>Actions by round</h3>
        <ol>
          <li v-for="row in activity" :key="row.round_num">
            <span>Round {{ row.round_num }}</span>
            <span class="social-round-bar" aria-hidden="true"><i :style="{ width: `${row.total_actions / maximum * 100}%` }"></i></span>
            <strong>{{ fmt(row.total_actions) }}</strong>
          </li>
        </ol>
      </section>
      <div v-if="posts.length" class="social-feed-controls">
        <label class="social-feed-search"><Search :size="15" aria-hidden="true" /><input v-model="query" type="search" aria-label="Search posts and replies" placeholder="Search posts and replies…" /></label>
        <select v-if="platforms.length > 1" v-model="platform" aria-label="Filter social platform"><option value="">All platforms</option><option v-for="item in platforms" :key="item">{{ item }}</option></select>
        <select v-if="rounds.length > 1" v-model="round" aria-label="Filter post round"><option value="">All rounds</option><option v-for="item in rounds" :key="item" :value="item">Round {{ item }}</option></select>
        <select v-model="sort" aria-label="Sort social posts"><option value="recorded">Saved order</option><option value="replies">Most replies</option><option value="likes">Most likes</option></select>
      </div>
      <div v-if="visible.length" class="social-posts">
        <SocialThread v-for="post in visible" :key="post.key" :post="post" :sentiment-method="story?.sentiment_method" />
        <WorkspacePager v-model:page="page" :size="size" :total="filtered.length" label="posts" />
      </div>
      <p v-else>{{ posts.length ? 'No posts match those filters.' : 'No posts were saved for this run.' }}</p>
    </template>
  </section>
</template>

<style scoped>
.social-feed-card { display: grid; gap: 12px; padding: 14px; min-width: 0; }
.social-feed-card > p { margin: 0; font-size: 12px; color: var(--muted); }
.social-rounds { padding: 12px; border: 1px solid var(--line); border-radius: 10px; }
.social-rounds h3 { margin: 0 0 7px; font-size: 14px; font-weight: 650; }
.social-rounds ol { list-style: none; display: grid; gap: 6px; padding: 0; margin: 0; max-height: 215px; overflow: auto; }
.social-rounds li { display: grid; grid-template-columns: 73px minmax(0,1fr) 64px; align-items: center; gap: 8px; font-size: 12px; font-variant-numeric: tabular-nums; }
.social-rounds strong { text-align: right; }
.social-round-bar { height: 5px; border-radius: 3px; background: var(--panel-2); overflow: hidden; }
.social-round-bar i { display: block; height: 100%; background: var(--accent); }
.social-feed-controls { display: flex; flex-wrap: wrap; gap: 7px; }
.social-feed-search, .social-feed-controls select { border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; background: var(--panel); color: var(--text); font-size: 12px; }
.social-feed-search { display: inline-flex; align-items: center; min-width: 170px; flex: 1; gap: 7px; }
.social-feed-search input { min-width: 0; width: 100%; }
.social-posts { display: grid; gap: 9px; }
</style>
