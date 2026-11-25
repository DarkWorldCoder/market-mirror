import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// The map search follows the ARIA 1.2 combobox pattern: the input is the combobox and points at its listbox
// and at the highlighted option, so screen readers announce the match while the arrow keys move.
const source = readFileSync(fileURLToPath(new URL('../../components/workspace/WorldFlowMap.vue', import.meta.url)), 'utf8')
const searchInput = source.match(/<input v-model="query"[\s\S]*?>/)?.[0] || ''

test('the search input is the combobox and points at its listbox and highlighted option', () => {
  assert.ok(/\srole="combobox"/.test(searchInput), 'search input must carry role="combobox"')
  assert.ok(/aria-controls="gm-suggest"/.test(searchInput), 'search input must carry aria-controls for the listbox')
  assert.ok(/:aria-activedescendant="[^"]*gm-opt-/.test(searchInput), 'search input must carry aria-activedescendant for the highlighted option')
  assert.ok(/:aria-expanded="/.test(searchInput), 'search input must carry aria-expanded')
})

test('the wrapper no longer claims the combobox role', () => {
  assert.ok(!/<div class="gm-search" role="combobox"/.test(source), 'the wrapper div must not keep role="combobox" or aria-owns')
})

test('each suggestion has the id the active descendant points to', () => {
  assert.ok(/<li v-for="\(sg, i\) in suggestions" :id="`gm-opt-\$\{i\}`"/.test(source), 'each option must have an id gm-opt-<index>')
})
