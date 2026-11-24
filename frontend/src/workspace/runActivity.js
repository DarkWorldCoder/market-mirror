// What the simulated people did in a saved run, read from its files with no model call: who replied to, liked or
// quoted whom (from the social feed, with the round), their per-person action counts, and plain-language sentences
// for a person card.
import { api } from './api'

const cache = new Map()

/** { edges, stats } for one run, loaded once (pass refresh while a run is going). */
export async function loadRunActivity(name, { refresh = false } = {}) {
  if (!refresh && cache.has(name)) return cache.get(name)
  const enc = encodeURIComponent(name)
  const run = await api(`/api/runs/${enc}`)
  const has = new Set(run.files || [])
  const get = (f) => (has.has(f) ? api(`/api/runs/${enc}/files/${f}`).catch(() => null) : Promise.resolve(null))
  const [story, statsRaw] = await Promise.all([get('feed_story.json'), get('agent_stats.json')])
  const out = { edges: feedEdges(story), stats: statsRaw ? (Array.isArray(statsRaw) ? statsRaw : statsRaw.agents || []) : [] }
  cache.set(name, out)
  return out
}

/** Interactions between people in the social feed. Brand and market-map accounts have no place on the map: a reply
 *  to them is marked toBrand and drawn as a pulse at the person. */
export function feedEdges(story) {
  const edges = []
  const person = (a) => a && a.kind === 'persona' && a.agent_id !== undefined && a.agent_id !== null
  for (const [platform, pl] of Object.entries(story?.platforms || {})) {
    for (const post of pl.posts || []) {
      const author = post.author
      const to = person(author) ? author.agent_id : null
      for (const c of post.comments || []) {
        if (person(c.author) && c.author.agent_id !== to) edges.push({ from: c.author.agent_id, to, toBrand: !person(author), kind: 'reply', round: c.round ?? post.round ?? null, platform, text: c.content || '', sentiment: c.sentiment })
      }
      for (const l of post.likers || []) {
        if (person(l) && l.agent_id !== to) edges.push({ from: l.agent_id, to, toBrand: !person(author), kind: 'like', round: post.round ?? null, platform })
      }
      // a quote or repost is its own post pointing at the original
      const orig = post.original?.author
      if ((post.kind === 'quote' || post.kind === 'repost') && orig && person(author) && orig.agent_id !== author.agent_id) {
        edges.push({ from: author.agent_id, to: person(orig) ? orig.agent_id : null, toBrand: !person(orig), kind: 'quote', round: post.round ?? null, platform, text: post.quote_content || post.content || '' })
      }
    }
  }
  return edges
}

/** "Wrote 1 comment and liked 2 comments on the Reddit-style site." from one person's action counts. */
export function describeActivity(stats) {
  if (!stats) return ''
  const words = {
    CREATE_POST: ['wrote', 'post'], CREATE_COMMENT: ['wrote', 'comment'], QUOTE_POST: ['quoted', 'post'], REPOST: ['shared', 'post'],
    LIKE_POST: ['liked', 'post'], LIKE_COMMENT: ['liked', 'comment'], DISLIKE_POST: ['disliked', 'post'], DISLIKE_COMMENT: ['disliked', 'comment'],
    FOLLOW: ['followed', 'person', 'people'], SEARCH_POSTS: ['searched', 'time'], UNLIKE_POST: ['took back a like on', 'post']
  }
  const parts = []
  for (const [type, n] of Object.entries(stats.action_types || {})) {
    const w = words[String(type).toUpperCase()]
    if (!w || !n) continue
    parts.push(`${w[0]} ${n} ${n === 1 ? w[1] : w[2] || w[1] + 's'}`)
  }
  if (!parts.length) return stats.total_actions ? `Took ${stats.total_actions} actions.` : 'Read the feeds but did not post, comment or like anything.'
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0]
  const where = stats.twitter_actions && stats.reddit_actions ? ' across both sites' : stats.reddit_actions ? ' on the Reddit-style site' : stats.twitter_actions ? ' on the Twitter-style site' : ''
  return `${list.charAt(0).toUpperCase()}${list.slice(1)}${where}.`
}

/** Would-buy answers in plain words. */
export const VERDICT = {
  yes: { label: 'Yes', tone: 'yes', note: 'Says they would buy or sign up.' },
  maybe: { label: 'Maybe', tone: 'maybe', note: 'Interested, but not convinced yet.' },
  no: { label: 'No', tone: 'no', note: 'Says they would not buy.' }
}
export const verdictOf = (v) => VERDICT[String(v || '').toLowerCase()] || (v ? { label: String(v), tone: 'maybe', note: '' } : null)

/** "create comment" -> "Commented" (the thought harvest stores the raw action name). */
export function plainDid(did) {
  const d = String(did || '').trim()
  const map = { 'create comment': 'Commented', 'create post': 'Posted', 'quote post': 'Quoted a post', repost: 'Shared a post', 'like post': 'Liked a post', 'like comment': 'Liked a comment' }
  return map[d.toLowerCase()] || (d ? d.charAt(0).toUpperCase() + d.slice(1) : '')
}
