import test from 'node:test'
import assert from 'node:assert/strict'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

test('feed posts show and announce the same total for reposts and quotes', async (t) => {
  const server = await createServer({
    configFile: false,
    plugins: [vue()],
    optimizeDeps: { noDiscovery: true },
    server: { middlewareMode: true, hmr: false, watch: null },
  })
  t.after(() => server.close())
  const { default: PlatformPost } = await server.ssrLoadModule('/src/components/workspace/PlatformPost.vue')
  for (const [counts, total] of [
    [{ quoteCount: 3 }, 3],
    [{ reposts: 1 }, 1],
    [{ reposts: 2, quoteCount: 4 }, 6],
    [{}, 0],
  ]) {
    const post = { who: 'Alex', platform: 'twitter', comments: [], ...counts }
    const html = await renderToString(createSSRApp(() => h(PlatformPost, { post })))
    const counter = html.match(/<span [^>]*aria-label="([^"]+ shares?)"[^>]*>([\s\S]*?)<\/span>/)
    assert.ok(counter, 'share count has an accessible label')
    assert.equal(counter[1], `${total} ${total === 1 ? 'share' : 'shares'}`)
    assert.equal(counter[2].replace(/<[^>]*>/g, '').trim(), String(total))
  }
})
