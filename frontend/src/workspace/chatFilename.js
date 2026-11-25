export function chatFilename(title, date = new Date()) {
  const clean = title.normalize('NFC').replace(/[^\p{L}\p{M}\p{N}_-]+/gu, '_')
  const stem = Array.from(clean.replace(/^_+/, '')).slice(0, 60).join('').replace(/_+$/, '')
  return /[\p{L}\p{N}]/u.test(stem) ? `${stem}.md` : `marketmirror-chat-${date.toISOString().slice(0, 10)}.md`
}
