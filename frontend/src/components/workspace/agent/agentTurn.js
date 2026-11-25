// Runs one chat-agent turn into an assistant message of ChatWorkspace. The message must be the reactive copy
// (messages.value.at(-1)) so every event re-renders its cards.
import { agentHistory, compareFromCards, newTurnState, reduceAgentEvent, streamAgent } from '../../../workspace/agentChat.js'

export { agentChatEnabled, markAnswered } from '../../../workspace/agentChat.js'

export function agentReply(id) {
  return { id, role: 'assistant', content: '', agent: newTurnState() }
}

export function agentBody({ sessionId, messages, model, run, project, files, resume }) {
  return {
    session_id: sessionId,
    messages: agentHistory(messages),
    ...(model ? { model } : {}),
    ...(run ? { run } : {}),
    ...(project ? { project } : {}),
    ...(files?.length ? { files } : {}),
    ...(resume ? { resume } : {})
  }
}

export async function runAgentTurn({ message, body, signal, onChange }) {
  try {
    const done = await streamAgent(body, { signal, onEvent: (name, data) => { reduceAgentEvent(message.agent, name, data); onChange?.() } })
    if (done.message) message.content = done.message
    if (done.suggestions?.length) message.suggestions = done.suggestions
    const compare = compareFromCards(message.agent.cards)
    if (compare) message.compare = compare      // rendered by the chat's embedded CompareRuns
    return done
  } catch (error) {
    if (message.agent.status !== 'error') {
      let explanation = error.message || 'Could not complete this response.'
      if (error.name === 'AbortError') {
        explanation = 'Stopped waiting for this response. Jobs already started keep running.'
      } else if (error instanceof TypeError && (
        error.message === 'Failed to fetch' ||
        error.message === 'NetworkError when attempting to fetch resource.'
      )) {
        explanation = 'The connection was interrupted. Try again.'
      }
      message.agent.status = 'error'
      message.agent.error = { message: explanation, actions: error.actions || [] }
    }
    return null
  } finally {
    onChange?.()
  }
}
