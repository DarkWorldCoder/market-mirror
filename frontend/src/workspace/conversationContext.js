function pageSource(page) {
  if (typeof page?.url !== 'string' || typeof page.text !== 'string' || !page.text.trim()) return null
  return { name: `Page: ${page.url}`, text: page.text }
}

// Give a page explicitly chosen for this question first claim on the context budget.
export function buildConversationContext(messages = [], pending = null, maximum = 24000, preferredPage = null) {
  const candidates = [
    pageSource(preferredPage),
    ...(pending?.files || []),
    ...[...messages].reverse().flatMap(message => [
      ...(message.attachedFiles || []),
      ...(message.browser_observations || [])
        .filter(page => !preferredPage || page?.url !== preferredPage.url)
        .map(pageSource),
      ...(message.tool_results || [])
        .filter(result => typeof result.result === 'string')
        .map(result => ({ name: `${result.connector}: ${result.tool}`, text: result.result }))
    ])
  ]
  const seen = new Set(), files = []
  let length = 0, omitted = 0
  for (const file of candidates) {
    if (typeof file?.name !== 'string' || typeof file.text !== 'string') continue
    const key = `${file.name}\0${file.text}`
    if (seen.has(key)) continue
    seen.add(key)
    const cost = `## ${file.name}\n${file.text}`.length + (files.length ? 2 : 0)
    if (length + cost > maximum) { omitted++; continue }
    files.push({ name: file.name, text: file.text }); length += cost
  }
  return { name: files.length === 1 ? files[0].name.slice(0,200) : `${files.length} conversation sources`, text: files.map(file => `## ${file.name}\n${file.text}`).join('\n\n'), files, omitted }
}
