<template>
  <div class="workflow-app" :class="{ embedded }">
    <a v-if="!embedded" class="skip-link" href="#workspace">Skip to content</a>
    <header v-if="!embedded" class="app-header">
      <RouterLink to="/" class="brand" @click="home" aria-label="MarketMirror home">
        <MarketMirrorLogo class="home-brand-mark" :size="28" />
        <span>MarketMirror</span><span class="home-app-tag">Workspace</span>
      </RouterLink>
      <nav aria-label="Main navigation">
        <a href="https://darkworldcoder.github.io/market-mirror/" target="_blank" rel="noopener noreferrer">Website</a>
        <RouterLink to="/workspace">Dashboard</RouterLink
        ><a :href="demo" target="_blank" rel="noopener noreferrer">Saved demo</a
        ><a
          :href="settings"
          target="_blank"
          rel="noopener noreferrer"
          @click="openSettings"
          >Model settings</a
        ><a
          href="https://github.com/DarkWorldCoder/market-mirror"
          target="_blank"
          rel="noopener noreferrer"
          >GitHub</a
        >
      </nav>
    </header>
    <main :id="embedded ? undefined : 'workspace'" class="app-main">
      <p v-if="error" class="notice error" role="alert">
        {{ error }}
        <button class="text-button" @click="error = ''">Dismiss</button>
      </p>
      <p v-if="message" class="notice" role="status">{{ message }}</p>
      <p v-if="!token" class="notice">
        Open this workspace with <code>./mm app</code> to connect securely to
        your local projects. The saved demo needs no provider.
      </p>
      <p v-if="settingsOpened" class="notice">
        Finished connecting a model?
        <button class="text-button" @click="refreshConnection">
          Refresh connection status
        </button>
      </p>

      <template v-if="screen === 'home'">
        <section v-if="!embedded" class="welcome" aria-labelledby="home-title">
          <div class="welcome-copy">
            <p class="local-label"><span aria-hidden="true"></span>Your local market rehearsal</p>
            <h1 id="home-title">Rehearse your<br />next move.</h1>
            <p class="welcome-subtitle">Before you go to market.</p>
            <p class="intro">Test ads, pricing and pitches with AI-simulated buyers. Explore their objections and decide what to test with real people.</p>
            <div class="actions">
              <RouterLink class="primary" to="/workspace"><LayoutDashboard :size="16" aria-hidden="true" />Open workspace</RouterLink>
              <button class="secondary" @click="begin('ads')"><Split :size="16" aria-hidden="true" />Compare two ideas</button>
            </div>
            <a class="home-demo-link" :href="demo" target="_blank" rel="noopener noreferrer">Explore the saved demo <ArrowUpRight :size="14" aria-hidden="true" /></a>
            <p class="small-note home-evidence-note">Simulated buyers. Inspectable results. Your real-world test comes next.</p>
          </div>
          <div class="rehearsal-preview" role="group" aria-label="Illustrative workflow showing product context, a simulated audience, and a saved decision report">
            <div class="preview-topline"><span><MarketMirrorLogo class="preview-mark" :size="20" />Inside a market rehearsal</span><span class="preview-label">Workflow preview</span></div>
            <div class="preview-brief"><span class="preview-icon"><FileText :size="18" aria-hidden="true" /></span><div><strong>Your product, in context</strong><p>Brief · Research · Two ideas</p></div><span class="preview-source-label">Start here</span></div>
            <div class="preview-connection" aria-hidden="true"></div>
            <div class="preview-audience">
              <div class="preview-person person-one"><UserRound :size="19" aria-hidden="true" /><span>Needs clarity</span></div>
              <div class="preview-person person-two"><UserRound :size="19" aria-hidden="true" /><span>Questions the price</span></div>
              <div class="preview-person person-three"><UserRound :size="19" aria-hidden="true" /><span>Looks for proof</span></div>
              <div class="preview-audience-label">A simulated audience with different points of view</div>
            </div>
            <div class="preview-connection" aria-hidden="true"></div>
            <div class="preview-report"><span class="preview-icon"><ChartNoAxesCombined :size="18" aria-hidden="true" /></span><div><strong>A direction you can inspect</strong><p>Responses, objections and a saved report</p></div><Files :size="17" aria-hidden="true" /></div>
            <div class="preview-bottomline"><span class="preview-check"><Check :size="13" aria-hidden="true" /></span>Choose the next experiment with real buyers.</div>
          </div>
        </section>
        <section v-if="!embedded" class="home-pathways" aria-label="Explore your workspace">
          <RouterLink to="/workspace/skills"><span class="home-pathway-icon"><Shapes :size="19" aria-hidden="true" /></span><div><strong>Choose a test</strong><span>Research, pricing, campaigns and sales</span></div><ChevronRight :size="16" aria-hidden="true" /></RouterLink>
          <RouterLink to="/workspace"><span class="home-pathway-icon"><UsersRound :size="19" aria-hidden="true" /></span><div><strong>Explore your audience</strong><span>Personas, market maps and activity</span></div><ChevronRight :size="16" aria-hidden="true" /></RouterLink>
          <RouterLink to="/workspace/reports"><span class="home-pathway-icon"><Files :size="19" aria-hidden="true" /></span><div><strong>Follow the evidence</strong><span>Every saved run, report and response</span></div><ChevronRight :size="16" aria-hidden="true" /></RouterLink>
        </section>
        <section>
          <div class="section-heading">
            <h2>What are you deciding?</h2>
            <RouterLink class="home-all-skills" to="/workspace/skills">Explore all skills <ArrowUpRight :size="14" aria-hidden="true" /></RouterLink>
          </div>
          <div
            v-for="group in recipeGroups"
            :key="group.name"
            class="recipe-group"
          >
            <h3 class="recipe-group-name">{{ group.name }}</h3>
            <div class="recipes-grid">
              <button
                v-for="recipe in group.recipes"
                :key="recipe.id"
                class="recipe"
                @click="begin(recipe.id)"
              >
                <span class="recipe-symbol" aria-hidden="true">{{
                  symbols[recipe.id]
                }}</span
                ><strong>{{ recipe.name }}</strong
                ><span>{{ recipe.question }}</span
                ><span class="recipe-arrow" aria-hidden="true">↗</span>
              </button>
            </div>
          </div>
        </section>
        <section class="recent">
          <div class="section-heading">
            <h2>Recent comparisons</h2>
            <RouterLink to="/workspace/reports">All saved reports</RouterLink>
          </div>
          <p v-if="!recent.length" class="empty-state">
            Start a comparison above. Your drafts and completed tests will
            appear here.
          </p>
          <RouterLink
            v-for="item in recent"
            :key="item.id"
            :to="embedded ? route.fullPath : `/workflows/${item.id}`"
            class="recent-row"
            @click.capture="embedded && ($event.preventDefault(), action(() => load(item.id)), emit('workflow', item.id))"
            ><div>
              <strong>{{ item.inputs.name || 'Untitled comparison' }}</strong
              ><span
                >{{ item.inputs.country || 'Draft' }} · Revision
                {{ item.revision }}</span
              >
            </div>
            <span>{{ statusLabel(item) }}</span
            ><span aria-hidden="true">↗</span></RouterLink
          >
        </section>
      </template>

      <template v-else>
        <div class="workspace-heading">
          <button class="text-button" @click="home">← All comparisons</button
          ><span>{{
            record
              ? `Revision ${record.revision} · Saved locally`
              : 'New comparison'
          }}</span>
        </div>
        <ol class="stepper" aria-label="Comparison progress">
          <li
            v-for="(label, index) in steps"
            :key="label"
            :class="{ current: stepIndex === index, done: stepIndex > index }"
            :aria-current="stepIndex === index ? 'step' : undefined"
          >
            <span>{{ index + 1 }}</span
            >{{ label }}
          </li>
        </ol>
        <div class="workspace-layout">
          <section class="editor">
            <div class="editor-heading">
              <p>{{ recipe.name }}</p>
              <h1 tabindex="-1">
                {{
                  screen === 'brief'
                    ? 'Tell us what is true.'
                    : screen === 'variants'
                      ? 'Put two ideas side by side.'
                      : results
                        ? 'A direction to investigate.'
                        : 'Review before model calls.'
                }}
              </h1>
            </div>
            <form
              v-if="screen === 'brief'"
              @submit.prevent="advance('variants')"
            >
              <label
                >Product name<input
                  v-model="inputs.name"
                  required
                  maxlength="120"
                  placeholder="Your product or business" /></label
              ><label
                >What does it do, and for whom?<textarea
                  v-model="inputs.product"
                  required
                  rows="3"
                  maxlength="5000"
                  placeholder="Describe the product in plain words. Include its actual price if relevant."
                ></textarea>
              </label>
              <details class="source-box">
                <summary>Bring details from a website or document</summary>
                <label
                  >Public product URL<input
                    v-model="inputs.source_url"
                    type="url"
                    placeholder="https://your-product.com" /></label
                ><button
                  class="secondary"
                  type="button"
                  :disabled="busy || !inputs.source_url"
                  @click="readUrl"
                >
                  Read page text</button
                ><label
                  >Or add a PDF, Markdown or text document<input
                    type="file"
                    accept=".pdf,.md,.txt"
                    @change="readFile"
                /></label>
                <p class="small-note">
                  No model calls. Reading a URL contacts that website. Review
                  imported text below.
                </p>
              </details>
              <label
                >Verified details and policies<textarea
                  v-model="inputs.facts"
                  rows="5"
                  maxlength="24000"
                  placeholder="Actual features, billing rules, shipping or returns. Correct any imported text."
                ></textarea>
              </label>
              <p
                v-if="['saas', 'ecommerce'].includes(inputs.recipe)"
                class="help"
              >
                This recipe needs your actual billing, shipping or return
                policies.
              </p>
              <div class="actions">
                <button class="primary" :disabled="busy">
                  Continue to ideas</button
                ><button
                  class="secondary"
                  type="button"
                  :disabled="busy"
                  @click="saveDraft"
                >
                  Save draft
                </button>
              </div>
            </form>
            <form
              v-if="screen === 'variants'"
              @submit.prevent="advance('review')"
            >
              <p class="help">{{ recipe.hint }}</p>
              <div class="variants-grid">
                <div
                  v-for="(variant, index) in inputs.variants"
                  :key="variant.id"
                  class="variant-editor"
                >
                  <label
                    ><span class="version-tag">{{ 'AB'[index] }}</span> Version
                    name<input
                      v-model="variant.label"
                      required
                      maxlength="80" /></label
                  ><label
                    >Message<textarea
                      v-model="variant.text"
                      rows="6"
                      required
                      maxlength="8000"
                      :placeholder="
                        index
                          ? 'The alternative version'
                          : 'Your current version'
                      "
                    ></textarea>
                  </label>
                </div>
              </div>
              <label
                >Who should consider this?<input
                  v-model="inputs.audience"
                  required
                  maxlength="1500"
                  placeholder="For example, busy parents looking for home workouts"
              /></label>
              <div class="field-pair">
                <label
                  >Country or market<input
                    v-model="inputs.country"
                    required
                    maxlength="120"
                    placeholder="For example, Nepal" /></label
                ><label
                  >Language<input
                    v-model="inputs.language"
                    required
                    maxlength="80"
                /></label>
              </div>
              <label
                >Evidence for claims, if used<textarea
                  v-model="inputs.claim_evidence"
                  rows="2"
                  maxlength="4000"
                  placeholder="Source for customer counts, testimonials, guarantees or cancellation terms. Leave empty if none."
                ></textarea>
              </label>
              <details>
                <summary>Audience and planning settings</summary>
                <div class="field-pair">
                  <label
                    >Simulated buyers<input
                      v-model.number="inputs.people"
                      type="number"
                      min="4"
                      max="60"
                      required /></label
                  ><label
                    >Channel<select v-model="inputs.platform">
                      <option v-for="p in platforms" :key="p" :value="p">
                        {{ p }}
                      </option>
                    </select></label
                  >
                </div>
                <div class="field-pair">
                  <label
                    >Advertising budget, optional<input
                      v-model.number="inputs.ad_budget"
                      type="number"
                      min="0"
                      step="0.01"
                      placeholder="Not model-call cost" /></label
                  ><label
                    >Currency<input v-model="inputs.currency" maxlength="8"
                  /></label>
                </div>
                <p class="small-note">
                  One seed. No social rounds, analyst panels or advertising
                  spend.
                </p>
              </details>
              <div class="actions">
                <button
                  class="secondary"
                  type="button"
                  @click="screen = 'brief'"
                >
                  Back</button
                ><button class="primary" :disabled="busy">
                  Review audience and costs</button
                ><button
                  class="text-button"
                  type="button"
                  :disabled="busy"
                  @click="saveDraft"
                >
                  Save draft
                </button>
              </div>
            </form>

            <template v-if="screen === 'review'">
              <div v-if="!results?.complete" class="review-facts">
                <strong>{{ inputs.name }}</strong>
                <p>{{ inputs.product }}</p>
                <p>
                  {{ inputs.audience }} · {{ inputs.country }} ·
                  {{ inputs.language }}
                </p>
                <div
                  v-for="variant in inputs.variants"
                  :key="variant.id"
                  class="review-variant"
                >
                  <strong>{{ variant.label }}</strong>
                  <p>{{ variant.text }}</p>
                </div>
              </div>
              <button
                class="text-button"
                :disabled="busy || running"
                @click="editComparison"
              >
                {{ hasHistory ? 'Edit as a new comparison' : 'Edit details' }}
              </button>
              <p v-if="!provider.configured" class="notice">
                Connect a model in
                <a
                  :href="settings"
                  target="_blank"
                  rel="noopener noreferrer"
                  @click="openSettings"
                  >Model settings</a
                >, then refresh the connection. Drafts and the saved demo need
                no provider.
              </p>
              <section v-if="!results?.complete" class="execution">
                <h2>
                  {{
                    prepared
                      ? 'Approve the comparison'
                      : 'Prepare a practice audience'
                  }}
                </h2>
                <p>
                  {{
                    prepared
                      ? 'Review the fictional people below. Both versions use the same people, with no memory carried between versions.'
                      : 'Preparing profiles uses model calls too. Review the estimate before generating anyone.'
                  }}
                </p>
                <p v-if="activeStage" class="stage-status" role="status">
                  {{ activeStage.status }} · {{ activeStage.calls_used }} /
                  {{ activeStage.call_limit }} calls reserved
                </p>
                <p v-if="activeStage?.error" class="notice error" role="alert">
                  {{ activeStage.error }}
                </p>
                <div v-if="running" role="status">
                  <p>{{ progress }}</p>
                  <p class="small-note">
                    You can close this page. Reopening does not start more model
                    calls.
                  </p>
                </div>
                <button
                  v-else-if="!quote"
                  class="secondary"
                  :disabled="busy || !provider.configured"
                  @click="reviewEstimate"
                >
                  {{
                    ['failed', 'interrupted'].includes(activeStage?.status)
                      ? 'Review remaining work'
                      : 'Review model-call estimate'
                  }}
                </button>
                <form v-else class="approval" @submit.prevent="approveCalls">
                  <h3>Cost unavailable</h3>
                  <p>{{ quote.explanation }}</p>
                  <dl>
                    <div>
                      <dt>Model</dt>
                      <dd>
                        {{
                          quote.provider.models[0]?.model || 'Not configured'
                        }}
                      </dd>
                    </div>
                    <div>
                      <dt>
                        Remaining {{ prepared ? 'exposures' : 'profiles' }}
                      </dt>
                      <dd>{{ quote.remaining_items }}</dd>
                    </div>
                    <div>
                      <dt>Estimated calls before retries</dt>
                      <dd>{{ quote.estimated_calls }} calls</dd>
                    </div>
                  </dl>
                  <label
                    >Total call limit for this stage<input
                      v-model.number="callLimit"
                      type="number"
                      :min="quote.calls_used + 1"
                      max="1000"
                      required
                  /></label>
                  <p class="small-note">
                    Includes {{ quote.calls_used }} calls already reserved. A
                    call limit is not a dollar cap. No advertising budget is
                    spent.
                  </p>
                  <label class="checkbox-label"
                    ><input v-model="consent" type="checkbox" required />I
                    approve these model calls using my connected
                    provider.</label
                  ><button class="primary" :disabled="busy || !consent">
                    {{
                      prepared
                        ? 'Approve and compare'
                        : 'Approve and prepare audience'
                    }}
                  </button>
                </form>
              </section>

              <section v-if="results" class="results">
                <span class="simulation-label"
                  >Simulated comparison{{
                    results.complete ? '' : ' · partial results'
                  }}</span
                >
                <h2>{{ results.verdict }}</h2>
                <p>{{ results.what_differed }}</p>
                <p class="help">{{ results.limits }}</p>
                <p
                  v-if="results.failed_exposures"
                  class="notice error"
                  role="status"
                >
                  {{ results.failed_exposures }} exposures returned no usable
                  answer and are excluded from scores. Review remaining work to
                  retry.
                </p>
                <div class="result-variants">
                  <article
                    v-for="variant in results.variants"
                    :key="variant.id"
                  >
                    <h3>{{ variant.label }}</h3>
                    <p class="result-number">
                      {{
                        variant.mean === null
                          ? 'Qualitative evidence'
                          : `${Math.round(variant.mean * 100)}%`
                      }}
                    </p>
                    <p class="small-note">
                      {{ results.metric_label }} · {{ variant.answered }} saved
                      exposures
                    </p>
                    <h4>Likely objections</h4>
                    <ul v-if="variant.objections.length">
                      <li
                        v-for="objection in variant.objections"
                        :key="objection"
                      >
                        {{ objection }}
                      </li>
                    </ul>
                    <p v-else>
                      No usable objections recorded. Review the detailed
                      evidence before drawing a conclusion.
                    </p>
                    <template v-if="variant.riskiest_phrases?.length">
                      <h4>Words that bothered people</h4>
                      <ul>
                        <li
                          v-for="item in variant.riskiest_phrases"
                          :key="item.phrase"
                        >
                          “{{ item.phrase }}” · {{ item.people }}
                        </li>
                      </ul>
                    </template>
                    <p
                      v-if="
                        variant.would_do && Object.keys(variant.would_do).length
                      "
                      class="small-note"
                    >
                      Would do:
                      {{
                        Object.entries(variant.would_do)
                          .map(([k, n]) => `${k.replaceAll('_', ' ')} ${n}`)
                          .join(' · ')
                      }}
                    </p>
                    <p
                      v-if="variant.fit && Object.keys(variant.fit).length"
                      class="small-note"
                    >
                      Think they qualify:
                      {{
                        Object.entries(variant.fit)
                          .map(([k, n]) => `${k} ${n}`)
                          .join(' · ')
                      }}
                    </p>
                    <p v-if="variant.moved_by?.length" class="small-note">
                      Moved by: {{ variant.moved_by.join(' · ') }}
                    </p>
                    <p v-if="variant.instead?.length" class="small-note">
                      Use today instead: {{ variant.instead.join(' · ') }}
                    </p>
                    <details v-if="variant.reactions.length">
                      <summary>AI-generated buyer reactions</summary>
                      <blockquote
                        v-for="reaction in variant.reactions"
                        :key="reaction"
                      >
                        {{ reaction }}
                      </blockquote>
                    </details>
                  </article>
                </div>
                <details>
                  <summary>How to read the comparison</summary>
                  <p class="help">{{ results.difference }}</p>
                  <p class="help">
                    Missing answers are not zero-interest votes. Errors remain
                    visible in run status.
                  </p>
                </details>
                <div class="next-test">
                  <h3>What to change and test next</h3>
                  <p>{{ results.next_action }}</p>
                  <a
                    href="https://darkworldcoder.github.io/market-mirror/guides/first-real-test/"
                    target="_blank"
                    rel="noopener noreferrer"
                    >See a worked real-world test</a
                  ><label
                    >Your real-test worksheet<textarea
                      v-model="worksheet"
                      rows="12"
                      maxlength="30000"
                    ></textarea>
                  </label>
                  <div class="actions">
                    <button
                      class="secondary"
                      :disabled="busy"
                      @click="saveWorksheet"
                    >
                      Save worksheet</button
                    ><button class="text-button" @click="downloadWorksheet">
                      Download Markdown
                    </button>
                  </div>
                </div>
                <button
                  class="text-button evidence-button"
                  :disabled="busy"
                  @click="openEvidence"
                >
                  Explore the evidence ↗
                </button>
              </section>
              <section v-if="record?.people.length" class="audience">
                <div class="section-heading">
                  <h2>Your simulated audience</h2>
                  <span>{{ record.people.length }} fictional people</span>
                </div>
                <div class="people-grid">
                  <article
                    v-for="person in record.people"
                    :key="person.agent_id"
                  >
                    <span class="person-initial" aria-hidden="true">{{
                      person.name?.slice(0, 1)
                    }}</span>
                    <h3>{{ person.name }}</h3>
                    <p>{{ person.age }} · {{ person.country }}</p>
                    <p>{{ person.occupation }}</p>
                    <details>
                      <summary>Background and concerns</summary>
                      <p>{{ person.persona }}</p>
                    </details>
                  </article>
                </div>
              </section>
            </template>
          </section>
          <aside>
            <h2>One decision at a time.</h2>
            <p>{{ recipe.question }}</p>
            <hr />
            <p>
              <strong>Keep the offer honest.</strong><br />Use actual features
              and policies. Add a source for proof claims.
            </p>
            <p>
              <strong>Rehearse, then validate.</strong><br />AI-generated buyers
              can help you spot questions. They cannot establish real customer
              demand.
            </p>
            <p class="small-note">
              Projects are saved on this computer. Model calls send product and
              audience context to your connected provider. Reading a source URL
              contacts that website.
            </p>
            <a :href="demo" target="_blank" rel="noopener noreferrer"
              >See the saved example</a
            >
          </aside>
        </div>
      </template>
    </main>
    <footer v-if="!embedded" class="app-footer">
      <span>MarketMirror · Open source · Local workspace</span>
      <div class="home-footer-links"><a href="https://darkworldcoder.github.io/market-mirror/" target="_blank" rel="noopener noreferrer">About MarketMirror</a><RouterLink to="/legacy">Legacy projects</RouterLink><span>Rehearse. Learn. Test with real people.</span></div>
    </footer>
  </div>
</template>

<script setup>
import MarketMirrorLogo from '../components/MarketMirrorLogo.vue'

import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowUpRight, ChartNoAxesCombined, Check, ChevronRight, Files, FileText, LayoutDashboard, Shapes, Split, UserRound, UsersRound } from 'lucide-vue-next'
// Inside the chat the setup runs as one step of the conversation: no page header, landing hero or address changes;
// the draft id is handed back to the chat message so reopening the chat reopens the draft.
const props = defineProps({ embedded: { type: Boolean, default: false }, initialWorkflow: { type: String, default: '' } })
const emit = defineEmits(['workflow'])
const route = useRoute(),
  router = useRouter()
const demo = 'https://darkworldcoder.github.io/market-mirror/demo/'
const steps = ['Product', 'Two ideas', 'Review and compare']
const platforms = ['instagram', 'facebook', 'tiktok', 'linkedin', 'x', 'reddit']
const symbols = {
  ads: 'A/B',
  landing: '▤',
  saas: '◷',
  ecommerce: '▱',
  email: '✉',
  committee: '◎',
  concept: '◇',
  statement: '❝',
  job: '⚑',
  appeal: '♡',
  regional: '文'
}
// Shown before the local backend answers; /api/workflows/meta replaces it (same ids, names and questions).
const recipes = ref(
  [
    ['ads', 'Ads or headlines', 'Which idea is clearer?'],
    ['landing', 'Landing-page clarity', 'Do people understand what I sell?'],
    ['email', 'Email subject and CTA', 'Which email communicates the offer?'],
    ['regional', 'Regional messaging', 'Does the wording make sense in this market?'],
    ['saas', 'SaaS trial offer', 'Is the billing or card requirement confusing?'],
    ['ecommerce', 'Ecommerce offer', 'Is shipping, price or returns causing hesitation?'],
    ['concept', 'Product or pack concept', 'Which idea would people buy?'],
    ['committee', 'B2B buying committee', 'What might the team question?'],
    ['statement', 'Announcement or crisis statement', 'Which wording keeps more trust?'],
    ['job', 'Job posting', 'Would the right people apply?'],
    ['appeal', 'Fundraising appeal', 'Which appeal moves people to give?']
  ].map(([id, name, question]) => ({ id, name, question, hint: '' }))
)
const groupOf = {
  ads: 'Ads, pages and emails',
  landing: 'Ads, pages and emails',
  email: 'Ads, pages and emails',
  regional: 'Ads, pages and emails',
  saas: 'Offers, products and sales',
  ecommerce: 'Offers, products and sales',
  concept: 'Offers, products and sales',
  committee: 'Offers, products and sales',
  statement: 'Announcements, hiring and fundraising',
  job: 'Announcements, hiring and fundraising',
  appeal: 'Announcements, hiring and fundraising'
}
const recipeGroups = computed(() => {
  const groups = []
  for (const recipe of recipes.value) {
    const name = groupOf[recipe.id] || 'More comparisons'
    let group = groups.find((g) => g.name === name)
    if (!group) groups.push((group = { name, recipes: [] }))
    group.recipes.push(recipe)
  }
  return groups
})
const token = ref(''),
  provider = ref({ configured: false, models: [] }),
  screen = ref('home')
const record = ref(null),
  recent = ref([]),
  quote = ref(null),
  results = ref(null),
  worksheet = ref('')
const busy = ref(false),
  error = ref(''),
  message = ref(''),
  consent = ref(false),
  callLimit = ref(120),
  settingsOpened = ref(false)
let timer,
  polling = false,
  activeSeconds = 0,
  lastActivity = Date.now()
const empty = (recipe = 'ads') => ({
  recipe,
  name: '',
  product: '',
  facts: '',
  source_url: '',
  audience: '',
  country: '',
  language: 'English',
  platform: 'instagram',
  people: 20,
  seed: 7,
  seeds: 1,
  ad_budget: null,
  currency: 'USD',
  claim_evidence: '',
  variants: [
    { id: 'v1', label: 'Version A', text: '' },
    { id: 'v2', label: 'Version B', text: '' }
  ]
})
const inputs = ref(empty())
const settings = computed(() => `/setup#t=${encodeURIComponent(token.value)}`)
const recipe = computed(
  () =>
    recipes.value.find((r) => r.id === inputs.value.recipe) || recipes.value[0]
)
const prepared = computed(
  () => record.value?.stages.prepare?.status === 'completed'
)
const phase = computed(() => (prepared.value ? 'test' : 'prepare'))
const activeStage = computed(() => record.value?.stages[phase.value])
const running = computed(() =>
  Object.values(record.value?.stages || {}).some((s) => s.status === 'running')
)
const hasHistory = computed(
  () => Object.keys(record.value?.stages || {}).length > 0
)
const stepIndex = computed(() =>
  screen.value === 'brief' ? 0 : screen.value === 'variants' ? 1 : 2
)
const progress = computed(() =>
  prepared.value
    ? `${Object.keys(record.value?.exposures || {}).length} of ${(record.value?.people.length || 0) * 2} exposures saved`
    : `${record.value?.people.length || 0} of ${inputs.value.people} fictional buyers prepared`
)
async function api(path = '', options = {}) {
  const response = await fetch(`/api/workflows${path}`, {
    ...options,
    headers: {
      'X-Setup-Token': token.value,
      ...(options.body instanceof FormData
        ? {}
        : { 'Content-Type': 'application/json' })
    },
    cache: 'no-store'
  })
  if (options.raw && response.ok) return response.text()
  const data = await response.json().catch(() => ({}))
  if (!response.ok || !data.success)
    throw new Error(
      response.status === 403
        ? 'Reopen this app with ./mm app on this computer to access your local workspace.'
        : data.error ||
          'Could not reach the local backend. Run ./mm app and try again.'
    )
  return data.data
}
const json = (method, body) => ({ method, body: JSON.stringify(body) })
async function action(work) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    return await work()
  } catch (e) {
    error.value =
      e.message === 'Failed to fetch'
        ? 'Connection to the local backend was lost. Run ./mm app, reopen the saved comparison, and retry.'
        : e.message || 'Could not complete that action. Try again.'
  } finally {
    busy.value = false
  }
}
function activity() {
  lastActivity = Date.now()
}
function localEvent(name, extra = {}) {
  if (token.value)
    api('/events', json('POST', { name, ...extra })).catch(() => {})
}
function openSettings() {
  settingsOpened.value = true
  localEvent('setup_opened')
}
function focusTitle() {
  requestAnimationFrame(() =>
    document.querySelector('.editor-heading h1')?.focus()
  )
}
function begin(kind) {
  record.value = null
  results.value = null
  worksheet.value = ''
  quote.value = null
  inputs.value = empty(kind)
  screen.value = 'brief'
  error.value = ''
  message.value = ''
  focusTitle()
}
function home() {
  screen.value = 'home'
  record.value = null
  results.value = null
  quote.value = null
  if (!props.embedded) router.push('/start')
  else emit('workflow', '')
  if (token.value)
    refreshRecent().catch((e) => {
      error.value = e.message
    })
}
async function refreshRecent() {
  recent.value = await api()
}
async function refreshConnection() {
  await action(async () => {
    const meta = await api('/meta')
    if (meta.provider.configured) localEvent('setup_connected')
    provider.value = meta.provider
    recipes.value = meta.recipes
    settingsOpened.value = false
    quote.value = null
    message.value = provider.value.configured
      ? 'Provider configured. Review the estimate before making model calls.'
      : 'No provider connected. Open Model settings to choose one.'
  })
}
function clean() {
  return {
    ...inputs.value,
    ad_budget: inputs.value.ad_budget === '' ? null : inputs.value.ad_budget
  }
}
async function persist() {
  const value = await api(
    record.value ? `/${record.value.id}` : '',
    json(record.value ? 'PUT' : 'POST', { inputs: clean() })
  )
  record.value = value
  if (props.embedded) emit('workflow', value.id)
  else await router.replace(`/workflows/${value.id}`)
  if (activeSeconds) {
    localEvent('active_seconds', {
      workflow_id: value.id,
      seconds: activeSeconds
    })
    activeSeconds = 0
  }
  return value
}
async function saveDraft() {
  await action(async () => {
    await persist()
    message.value = 'Draft saved on this computer.'
  })
}
async function advance(next) {
  await action(async () => {
    if (
      next === 'variants' &&
      inputs.value.recipe === 'landing' &&
      !inputs.value.variants[0].text &&
      inputs.value.facts
    ) {
      inputs.value.variants[0].text = inputs.value.facts.slice(0, 8000)
    }
    await persist()
    screen.value = next
    quote.value = null
    focusTitle()
  })
}
async function editComparison() {
  if (!hasHistory.value) {
    screen.value = 'brief'
    quote.value = null
    return
  }
  await action(async () => {
    record.value = await api(
      '',
      json('POST', { inputs: clean(), parent_id: record.value.id })
    )
    results.value = null
    quote.value = null
    worksheet.value = ''
    screen.value = 'brief'
    if (props.embedded) emit('workflow', record.value.id)
    else await router.replace(`/workflows/${record.value.id}`)
    focusTitle()
  })
}
async function readUrl() {
  await action(async () => {
    const value = await api(
      '/source',
      json('POST', { url: inputs.value.source_url })
    )
    inputs.value.facts = value.text
    message.value =
      'Page text imported. Correct and remove irrelevant text before continuing.'
  })
}
async function readFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  await action(async () => {
    const form = new FormData()
    form.append('file', file)
    const value = await api('/source', { method: 'POST', body: form })
    inputs.value.facts = [inputs.value.facts, value.text]
      .filter(Boolean)
      .join('\n\n')
      .slice(0, 24000)
    message.value = 'Document imported. Review the text before testing.'
  })
  event.target.value = ''
}
async function reviewEstimate() {
  await action(async () => {
    await persist()
    quote.value = await api(
      `/${record.value.id}/estimate`,
      json('POST', { phase: phase.value })
    )
    callLimit.value = quote.value.suggested_call_limit
    consent.value = false
  })
}
async function approveCalls() {
  await action(async () => {
    if (!consent.value || !quote.value) return
    const stage = phase.value
    record.value = await api(
      `/${record.value.id}/approve`,
      json('POST', {
        approved: true,
        phase: stage,
        digest: quote.value.digest,
        call_limit: callLimit.value,
        retry: ['failed', 'interrupted'].includes(activeStage.value?.status)
      })
    )
    quote.value = null
    consent.value = false
    message.value =
      stage === 'prepare'
        ? 'Preparing the approved audience. Testing needs a separate approval.'
        : 'Comparison started. You can return later.'
  })
}
async function load(id) {
  const value = await api(`/${id}`)
  record.value = value
  inputs.value = structuredClone(value.inputs)
  screen.value = Object.keys(value.stages).length ? 'review' : 'brief'
  quote.value = null
  results.value = null
  worksheet.value = ''
  await loadResults()
}
async function loadResults() {
  if (!record.value || !Object.keys(record.value.exposures).length) return
  results.value = await api(`/${record.value.id}/results`)
  if (!worksheet.value) worksheet.value = results.value.worksheet
}
async function poll() {
  if (polling || busy.value || !record.value || !running.value) return
  polling = true
  try {
    record.value = await api(`/${record.value.id}`)
    await loadResults()
    if (!running.value) {
      quote.value = null
      consent.value = false
      message.value =
        prepared.value && !record.value.stages.test
          ? 'Audience prepared. Review the fictional people, then approve the comparison separately.'
          : 'Progress saved.'
    }
  } catch (e) {
    error.value = e.message
  } finally {
    polling = false
  }
}
async function saveWorksheet() {
  await action(async () => {
    await api(
      `/${record.value.id}/worksheet`,
      json('PUT', { text: worksheet.value })
    )
    message.value = 'Worksheet saved locally.'
  })
}
function downloadWorksheet() {
  const url = URL.createObjectURL(
    new Blob([worksheet.value], { type: 'text/markdown' })
  )
  const a = document.createElement('a')
  a.href = url
  a.download = 'marketmirror-real-test.md'
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function openEvidence() {
  await action(async () => {
    const content = await api(`/${record.value.id}/evidence`, { raw: true })
    const url = URL.createObjectURL(new Blob([content], { type: 'text/html' }))
    window.open(url, '_blank', 'noopener,noreferrer')
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  })
}
function statusLabel(item) {
  const stage = item.stages.test || item.stages.prepare
  return stage
    ? `${item.stages.test ? 'Comparison' : 'Audience'} ${stage.status}`
    : 'Draft'
}
watch(
  () => route.params.workflowId,
  (id) => {
    if (id && !props.embedded) action(() => load(id))
  }
)
onMounted(async () => {
  const supplied = new URLSearchParams(location.hash.slice(1)).get('t')
  try {
    token.value =
      supplied || sessionStorage.getItem('marketmirror-session') || ''
    if (supplied) sessionStorage.setItem('marketmirror-session', supplied)
  } catch {
    token.value = supplied || ''
  }
  if (supplied)
    window.history.replaceState(
      window.history.state,
      '',
      location.pathname + location.search
    )
  if (token.value)
    await action(async () => {
      const meta = await api('/meta')
      recipes.value = meta.recipes
      provider.value = meta.provider
      await refreshRecent()
      const startId = props.embedded ? props.initialWorkflow : route.params.workflowId
      if (startId) await load(startId)
    })
  document.addEventListener('keydown', activity)
  document.addEventListener('pointerdown', activity)
  timer = setInterval(() => {
    if (
      screen.value !== 'home' &&
      !running.value &&
      document.visibilityState === 'visible' &&
      Date.now() - lastActivity < 60000
    )
      activeSeconds++
    poll()
  }, 1000)
})
onUnmounted(() => {
  clearInterval(timer)
  document.removeEventListener('keydown', activity)
  document.removeEventListener('pointerdown', activity)
})
</script>

<style scoped src="../assets/workflows.css"></style>
