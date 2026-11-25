import { onScopeDispose, ref } from 'vue'

export function useChatCopyFeedback(onError) {
  const copiedMessage = ref('')
  let resetTimer
  let latestCopy = 0

  onScopeDispose(() => {
    latestCopy++
    clearTimeout(resetTimer)
  })

  async function copyMessage(message) {
    const copy = ++latestCopy
    try {
      await navigator.clipboard.writeText(message.content)
    } catch {
      if (copy === latestCopy) onError()
      return
    }
    if (copy !== latestCopy) return

    clearTimeout(resetTimer)
    copiedMessage.value = message.id
    resetTimer = setTimeout(() => { copiedMessage.value = '' }, 2000)
  }

  return { copiedMessage, copyMessage }
}
