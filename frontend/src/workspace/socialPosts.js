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
