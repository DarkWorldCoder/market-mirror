// A small Markdown subset for chat answers (headings, bold, italic, inline code, code blocks, lists, quotes,
// paragraphs). Every character is HTML-escaped first and only these tags are added afterwards, so model text can
// never inject markup or links. Links stay as plain text on purpose.

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

function inline(s) {
  return s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>')
    .replace(/(^|[\s(])_([^_\s][^_]*)_(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>')
}

export function renderMarkdown(text) {
  const lines = esc(text || '').replace(/\r\n?/g, '\n').split('\n')
  const out = []
  let list = null, para = [], code = null

  const flushPara = () => {
    if (para.length) out.push(`<p>${inline(para.join('<br>'))}</p>`)
    para = []
  }
  const flushList = () => {
    if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`)
    list = null
  }

  for (const raw of lines) {
    const line = raw.trimEnd()
    if (code !== null) {
      if (/^\s*```/.test(line)) {
        out.push(`<pre><code>${code.join('\n')}</code></pre>`)
        code = null
      } else code.push(raw)
      continue
    }
    if (/^\s*```/.test(line)) {
      flushPara()
      flushList()
      code = []
      continue
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/)
    const ul = line.match(/^\s*[-*•]\s+(.*)$/)
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/)
    const quote = line.match(/^\s*&gt;\s?(.*)$/)
    if (!line.trim()) {
      flushPara()
      flushList()
    } else if (h) {
      flushPara()
      flushList()
      const level = Math.min(6, h[1].length + 2) // chat headings stay small: # -> h3
      out.push(`<h${level}>${inline(h[2])}</h${level}>`)
    } else if (ul || ol) {
      flushPara()
      const tag = ul ? 'ul' : 'ol'
      if (!list || list.tag !== tag) {
        flushList()
        list = { tag, items: [] }
      }
      list.items.push((ul || ol)[1])
    } else if (quote) {
      flushPara()
      flushList()
      out.push(`<blockquote>${inline(quote[1])}</blockquote>`)
    } else if (/^\s*(---|\*\*\*)\s*$/.test(line)) {
      flushPara()
      flushList()
      out.push('<hr>')
    } else {
      flushList()
      para.push(line)
    }
  }
  if (code !== null) out.push(`<pre><code>${code.join('\n')}</code></pre>`)
  flushPara()
  flushList()
  return out.join('')
}
