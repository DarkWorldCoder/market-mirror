// Prefer enriched feed-story rows, adding raw exports only when a platform's story is missing or truncated.
export function socialPosts(story, rawByPlatform = {}, personas = []) {
  const names = new Map(personas.map(person => [String(person.agent_id), person.name]))
  const rows = [], seen = new Set()
  function add(post, platform) {
    if (!post || typeof post !== 'object') return
    const content = post.content || post.text || '', quote = post.quote_content || ''
    const id = post.post_id ?? post.id
    const key = id != null ? `${platform}:${id}` : `${platform}:${post.author?.agent_id ?? post.user_id ?? post.author}:${content}:${quote}`
    if (seen.has(key)) return
    seen.add(key)
    const author = post.author
    const who = (author && typeof author === 'object' ? author.name : author) || post.name || post.agent_name || names.get(String(post.user_id ?? post.agent_id)) || `Agent ${post.user_id ?? post.agent_id ?? 'unknown'}`
    rows.push({
      key, id, who, platform: post.platform || platform || 'Unspecified platform',
      text: content || (post.original_post_id != null ? '' : 'No post text recorded.'),
      quote, originalPostId: post.original_post_id ?? null,
      score: post.score ?? post.net_score ?? (Number.isFinite(post.num_likes) && Number.isFinite(post.num_dislikes) ? post.num_likes - post.num_dislikes : null),
      comments: Array.isArray(post.comments) ? post.comments : [],
      round: post.round ?? null,
      likes: post.likes ?? post.num_likes,
      dislikes: post.dislikes ?? post.num_dislikes,
      country: post.author?.country,
      segment: post.author?.segment,
      replySentiment: post.reply_sentiment,
      // for platform-style cards
      kind: post.kind || (post.original_post_id != null ? (quote ? 'quote' : 'repost') : 'post'),
      authorKind: author && typeof author === 'object' ? author.kind || null : null,
      isBrand: Boolean(post.is_brand) || (author && typeof author === 'object' && author.kind === 'graph'),
      original: post.original?.author ? { who: post.original.author.name || 'Someone', postId: post.original.post_id ?? null } : null,
      reposts: Number.isFinite(post.reposts) ? post.reposts : null,
      quoteCount: Array.isArray(post.quotes) ? post.quotes.length : Number.isFinite(post.quotes) ? post.quotes : null,
      hour: post.hour || null,
    })
  }
  if (Array.isArray(story)) for (const post of story) add(post, post.platform || '')
  else {
    const platforms = story?.platforms
    if (platforms && typeof platforms === 'object') for (const [platform, data] of Object.entries(platforms)) for (const post of (Array.isArray(data) ? data : data?.posts || [])) add(post, platform)
    for (const post of story?.posts || story?.items || []) add(post, post.platform || '')
  }
  for (const [platform, raw] of Object.entries(rawByPlatform)) for (const post of (Array.isArray(raw) ? raw : raw?.posts || [])) add(post, platform)
  return rows
}
export function neededRawPosts(story, availableFiles) {
  const available = new Set(availableFiles || [])
  return ['twitter', 'reddit'].filter(platform => {
    if (!available.has(`posts_${platform}.json`)) return false
    const data = story?.platforms?.[platform]
    const topLevel = Array.isArray(story) ? story : story?.posts || story?.items || []
    const hasPosts = data && Array.isArray(Array.isArray(data) ? data : data.posts)
    return data?.truncated || (Number.isFinite(data?.total_posts) && data.total_posts > (data.posts?.length || 0)) || (!hasPosts && !topLevel.some(post => post.platform === platform))
  })
}

const PLATFORM_LABELS = { twitter: 'Twitter-style', reddit: 'Reddit-style', facebook: 'Facebook-style', instagram: 'Instagram-style', linkedin: 'LinkedIn-style', tiktok: 'TikTok-style', youtube: 'YouTube-style', x: 'Twitter-style' }
/** "Twitter-style", "Reddit-style"… a layout label only, never the platform's branding. */
export const platformStyle = (platform) => PLATFORM_LABELS[String(platform || '').toLowerCase()] || (platform ? `${String(platform).charAt(0).toUpperCase()}${String(platform).slice(1)}-style` : 'Feed')

/** Feed-test ads with what the simulated people did when each one appeared in their feed (first seed only). */
export function feedAds(feedTest) {
  const creatives = Array.isArray(feedTest?.creatives) ? feedTest.creatives : []
  if (!creatives.length) return []
  const seed = feedTest.seed
  const sessions = (Array.isArray(feedTest.sessions) ? feedTest.sessions : []).filter((s) => s && (seed === undefined || s.seed === undefined || s.seed === seed))
  const per = feedTest.summary?.per_creative || {}
  return creatives.map((c) => {
    const mine = sessions.filter((s) => s.creative_id === c.id)
    const count = (fn) => mine.filter((s) => fn(s.ad || {})).length
    const clicked = count((a) => a.click), hid = count((a) => a.hide && !a.click)
    const stopped = count((a) => a.stopped && !a.click && !a.hide)
    const thoughts = mine.filter((s) => String(s.ad?.thought || '').trim()).slice(0, 4).map((s) => ({ who: s.name || `Person ${s.agent_id}`, segment: s.segment || '', text: String(s.ad.thought).trim(),
      did: s.ad.hide ? 'Hid the ad' : s.ad.click ? 'Clicked' : s.ad.stopped ? 'Stopped, then scrolled on' : 'Scrolled past' }))
    return {
      id: c.id, name: c.name || c.id, platform: String(c.platform || '').toLowerCase(), page: c.page || '', headline: c.headline || '', text: c.text || '', cta: c.cta || '',
      media: c.media || '', format: c.format || '', link: c.link || '',
      shown: mine.length, clicked, hid, stopped, scrolled: Math.max(0, mine.length - clicked - hid - stopped),
      expectedCtr: Number.isFinite(per[c.id]?.expected_ctr) ? per[c.id].expected_ctr : null, thoughts
    }
  })
}
