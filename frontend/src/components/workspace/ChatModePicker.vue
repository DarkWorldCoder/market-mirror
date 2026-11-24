<script setup>
import { computed, ref } from 'vue'
import { ClipboardPlus, MessageSquare, Sparkles, UsersRound } from 'lucide-vue-next'
import { Popover, PopoverContent, PopoverTrigger } from '../ui/popover'
import { Button } from '../ui/button'
import { resultsReview } from '../../workspace/teamReview'

const props = defineProps({
  modelValue: { default: 'standard' },
  disabled: Boolean,
  theme: { default: 'light' },
  agents: { type: Array, default: () => ['market-analyst', 'critical-reviewer'] },
  agentModels: { type: Object, default: () => ({}) },
  models: { type: Array, default: () => [] },
  canComment: Boolean
})
const emit = defineEmits(['update:modelValue', 'update:agents', 'update:agentModels', 'use-brief'])
const open = ref(false)
const feedback = ref('')
let inserting = false

const modes = [
  { id: 'standard', title: 'Solo', icon: Sparkles, description: 'A direct answer from your selected model.' },
  { id: 'team', title: 'Team review', icon: UsersRound, description: 'Specialists review the first answer before your chat model combines their findings.' },
  { id: 'note', title: 'Team note', icon: MessageSquare, description: 'Share a note with teammates without invoking a model.' }
]
const visibleModes = computed(() => props.canComment ? modes : modes.slice(0, 2))
const activeMode = computed(() => visibleModes.value.find(mode => mode.id === props.modelValue) || modes[0])
const roles = [
  { id: 'market-analyst', name: 'Market analyst', description: 'Audience fit and commercial implications.' },
  { id: 'critical-reviewer', name: 'Critical reviewer', description: 'Unsupported claims and gaps in evidence.' },
  { id: 'audience-researcher', name: 'Audience researcher', description: 'Buyer motivations, language and segments.' },
  { id: 'ads-strategist', name: 'Ads strategist', description: 'Creative hypotheses and campaign fit.' },
  { id: 'data-analyst', name: 'Data analyst', description: 'Comparisons, sample sizes and uncertainty.' },
  { id: 'product-strategist', name: 'Product strategist', description: 'Product value and positioning.' },
  { id: 'conversion-specialist', name: 'Conversion specialist', description: 'Landing-page messaging, trust and friction.' },
  { id: 'pricing-analyst', name: 'Pricing analyst', description: 'Pricing, packaging and willingness to pay.' },
  { id: 'competitive-analyst', name: 'Competitive analyst', description: 'Alternatives and differentiation.' },
  { id: 'lifecycle-strategist', name: 'Lifecycle strategist', description: 'Onboarding, activation and retention.' },
  { id: 'measurement-specialist', name: 'Measurement specialist', description: 'Tracking, attribution and experiment design.' }
]
const cases = [
  {
    id: 'ads', title: 'Compare ad creatives', roles: ['ads-strategist', 'audience-researcher', 'measurement-specialist'],
    prompt: 'Compare the ad variants I provide. For each one, identify the audience, hook and proof, then recommend a test with one primary metric and a guardrail. Use any supplied performance data and call out gaps.'
  },
  {
    id: 'landing', title: 'Review a landing page', roles: ['conversion-specialist', 'audience-researcher', 'competitive-analyst'],
    prompt: 'Review the landing page I provide. Check whether its promise, proof and call to action match the target audience. Recommend three specific changes and one test. If I have not provided a URL or page copy, ask for it.'
  },
  {
    id: 'pricing', title: 'Evaluate a price or trial', roles: ['pricing-analyst', 'conversion-specialist', 'data-analyst'],
    prompt: 'Evaluate the price, packaging or trial I describe. Explain the likely conversion and revenue trade-offs. Use supplied evidence to identify objections, then propose one measurable pricing experiment.'
  },
  {
    id: 'positioning', title: 'Find a positioning angle', roles: ['competitive-analyst', 'product-strategist', 'audience-researcher'],
    prompt: 'Assess our positioning against the alternatives I provide. Identify the buyer, their main problem, a credible point of difference and the proof we need to make the claim.'
  },
  {
    id: 'lifecycle', title: 'Improve activation or retention', roles: ['lifecycle-strategist', 'conversion-specialist', 'measurement-specialist'],
    prompt: 'Review the onboarding or retention flow I describe. Identify where a specific audience drops off, propose a message and trigger, and define how to measure the result.'
  },
  resultsReview
]
const preset = computed(() => cases.find(item =>
  item.roles.length === props.agents.length && item.roles.every(id => props.agents.includes(id))
))
const selectedRoles = computed(() => props.agents.map(id => roles.find(role => role.id === id)).filter(Boolean))
const availableModels = computed(() => props.models.filter(model => model.available !== false))

function updateTeam(ids) {
  feedback.value = ''
  emit('update:agents', ids)
  emit('update:agentModels', Object.fromEntries(Object.entries(props.agentModels).filter(([id]) => ids.includes(id))))
}
function chooseCase(id) {
  const item = cases.find(item => item.id === id)
  if (item) updateTeam(item.roles)
}
function toggle(id, event) {
  const checked = props.agents.includes(id)
  if (checked && props.agents.length <= 2) {
    event.target.checked = true
    feedback.value = 'Add another reviewer before removing this one.'
    return
  }
  if (!checked && props.agents.length >= 4) {
    event.target.checked = false
    feedback.value = 'Remove a reviewer to make room for this one.'
    return
  }
  updateTeam(checked ? props.agents.filter(role => role !== id) : [...props.agents, id])
}
function changeModel(id, value) {
  const models = { ...props.agentModels }
  if (value) models[id] = value
  else delete models[id]
  emit('update:agentModels', models)
}
function useBrief() {
  if (!preset.value) return
  inserting = true
  open.value = false
  emit('use-brief', preset.value.prompt)
}
function restoreFocus(event) {
  if (!inserting) return
  event.preventDefault()
  inserting = false
}
</script>

<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child>
      <button class="chat-mode-trigger" :disabled="disabled" :aria-label="modelValue === 'team' ? 'Configure team reviewers' : 'Choose answer mode'">
        <component :is="activeMode.icon" :size="14" aria-hidden="true" />
        <span>{{ modelValue === 'team' ? 'Team' : modelValue === 'note' ? 'Note' : 'Solo' }}</span>
      </button>
    </PopoverTrigger>
    <PopoverContent
      align="end" side="top" :collision-padding="12" :side-offset="8"
      class="ws-overlay chat-mode-popup" :data-theme="theme" aria-label="Chat response mode"
      @close-auto-focus="restoreFocus"
    >
      <div class="chat-mode-options workspace-modal-tabs" role="group" aria-label="Response mode">
        <button v-for="mode in visibleModes" :key="mode.id" :disabled="disabled" :aria-pressed="modelValue === mode.id" @click="emit('update:modelValue', mode.id)">
          <component :is="mode.icon" :size="14" aria-hidden="true" />{{ mode.title }}
        </button>
      </div>
      <p class="team-description">{{ activeMode.description }}</p>
      <template v-if="modelValue === 'team'">
        <div class="team-use-case">
          <label>
            <span>Use case</span>
            <select :value="preset?.id || ''" :disabled="disabled" @change="chooseCase($event.target.value)">
              <option value="" disabled>Choose a use case</option>
              <option v-for="item in cases" :key="item.id" :value="item.id">{{ item.title }}</option>
            </select>
          </label>
          <Button v-if="preset" variant="outline" size="sm" :disabled="disabled" @click="useBrief">
            <ClipboardPlus :size="14" />Add brief to draft
          </Button>
        </div>
        <h3>Reviewers <small>{{ agents.length }} of 4</small></h3>
        <ul class="team-reviewer-list">
          <li v-for="role in selectedRoles" :key="role.id">
            <div><strong>{{ role.name }}</strong><span>{{ role.description }}</span></div>
            <select :aria-label="`Model for ${role.name}`" :value="agentModels[role.id] || ''" :disabled="disabled" @change="changeModel(role.id, $event.target.value)">
              <option value="">Use chat model</option>
              <option v-if="agentModels[role.id] && !availableModels.some(model => model.id === agentModels[role.id])" :value="agentModels[role.id]" disabled>Saved model unavailable</option>
              <option v-for="model in availableModels" :key="model.id" :value="model.id">{{ model.name || model.model }}</option>
            </select>
          </li>
        </ul>
        <details class="team-customize">
          <summary>Customize reviewers</summary>
          <label v-for="role in roles" :key="role.id">
            <input type="checkbox" :checked="agents.includes(role.id)" :disabled="disabled" @change="toggle(role.id, $event)" />
            <span><strong>{{ role.name }}</strong><small>{{ role.description }}</small></span>
          </label>
          <p v-if="feedback" class="team-feedback" role="status">{{ feedback }}</p>
        </details>
        <p class="team-cost">Up to {{ agents.length + 1 }} additional model calls. Your spending limits apply.</p>
      </template>
    </PopoverContent>
  </Popover>
</template>

<style>
.ws .direct-chat .direct-composer-options > button.chat-mode-trigger {
  display: inline-flex; align-items: center; gap: 6px; min-height: 30px; padding: 6px 8px;
  border-radius: 8px; color: var(--muted); font-size: 12px; line-height: 18px;
}
.ws .direct-chat .direct-composer-options > button.chat-mode-trigger:hover { background: var(--panel-2); color: var(--text); }
.chat-mode-popup.ws-overlay {
  width: min(410px, calc(100vw - 24px)); max-height: min(530px, var(--reka-popover-content-available-height, 530px));
  overflow: auto; overscroll-behavior: contain; scrollbar-width: thin; padding: 14px;
  border-radius: 14px; background: var(--panel); border-color: var(--line); color: var(--text); font-size: 13px;
}
.chat-mode-popup .chat-mode-options { display: flex; gap: 4px; padding: 3px; background: var(--panel-2); border-radius: 11px; }
.chat-mode-popup .chat-mode-options > button { display: inline-flex; flex: 1; align-items: center; justify-content: center; gap: 6px; padding: 6px; cursor: pointer; }
.chat-mode-popup .team-description { color: var(--muted); line-height: 1.5; margin: 9px 0 0; text-wrap: pretty; }
.chat-mode-popup .team-use-case { display: flex; align-items: flex-end; flex-wrap: wrap; gap: 8px; margin: 14px 0; }
.chat-mode-popup .team-use-case label { display: grid; gap: 5px; flex: 1; min-width: 150px; font-weight: 550; }
.chat-mode-popup select {
  min-width: 0; max-width: 100%; height: 36px; padding: 5px 8px; border: 1px solid var(--line);
  border-radius: 8px; background: var(--panel); color: var(--text); font-size: 12px;
}
.chat-mode-popup .team-use-case button { height: 36px; font-size: 12px; }
.chat-mode-popup h3 { display: flex; align-items: center; justify-content: space-between; font-size: 13px; font-weight: 600; margin: 14px 0 7px; }
.chat-mode-popup h3 small { font-size: 11px; font-weight: 400; color: var(--muted); }
.chat-mode-popup .team-reviewer-list { margin: 0; padding: 0; list-style: none; border: 1px solid var(--line); border-radius: 10px; }
.chat-mode-popup .team-reviewer-list li { display: grid; grid-template-columns: minmax(0,1fr) minmax(100px,37%); gap: 8px; align-items: center; padding: 9px; }
.chat-mode-popup .team-reviewer-list li + li { border-top: 1px solid var(--line); }
.chat-mode-popup strong { font-size: 12px; font-weight: 600; }
.chat-mode-popup .team-reviewer-list li span, .chat-mode-popup .team-customize small { display: block; font-size: 11px; line-height: 1.45; color: var(--muted); }
.chat-mode-popup .team-customize { margin-top: 10px; padding: 8px 9px; border: 1px solid var(--line); border-radius: 9px; }
.chat-mode-popup .team-customize summary { cursor: pointer; font-size: 12px; font-weight: 550; }
.chat-mode-popup .team-customize label { display: flex; align-items: flex-start; gap: 8px; padding: 7px 0; cursor: pointer; }
.chat-mode-popup input[type=checkbox] { width: 15px; height: 15px; flex-shrink: 0; accent-color: var(--accent); }
.chat-mode-popup .team-feedback, .chat-mode-popup .team-cost { font-size: 11px; line-height: 1.5; color: var(--muted); margin: 9px 0 0; }
.chat-mode-popup :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>
