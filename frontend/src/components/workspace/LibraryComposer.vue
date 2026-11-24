<template>
  <div ref="host" class="library-composer" data-library="21st.dev Agent Elements InputBar"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { ComposerIsland } from '../agent-elements/ComposerIsland'

const props = defineProps({
  disabled: Boolean,
  busy: Boolean,
  placeholder: { type: String, default: 'Ask about your market, reports or next test…' },
  modelValue: { type: String, default: undefined },
  models: { type: Array, default: () => [] },
  selectedModel: { type: String, default: '' },
  changing: Boolean
})
const emit = defineEmits(['send', 'stop', 'update:modelValue', 'model-change', 'attach', 'connectors', 'choose-run', 'skills', 'settings', 'browser'])
const host = ref(null), externalValue = ref(props.modelValue), revision = ref(0)
let root
function render() {
  if (!root) return
  root.render(createElement(ComposerIsland, {
    disabled: props.disabled,
    busy: props.busy,
    placeholder: props.placeholder,
    value: externalValue.value,
    revision: revision.value,
    models: props.models,
    selectedModel: props.selectedModel,
    changing: props.changing,
    onModelChange: id => emit('model-change', id),
    onAttach: () => emit('attach'),
    onConnectors: () => emit('connectors'),
    onChooseRun: () => emit('choose-run'),
    onSkills: () => emit('skills'),
    onSettings: () => emit('settings'),
    onBrowser: () => emit('browser'),
    onChange: value => emit('update:modelValue', value),
    onSend: content => emit('send', content),
    onStop: () => emit('stop')
  }))
}
watch(() => props.modelValue, value => { externalValue.value = value; render() })
watch(() => [props.disabled, props.busy, props.placeholder, props.models, props.selectedModel, props.changing], render, { deep: true })
onMounted(() => { root = createRoot(host.value); render() })
onBeforeUnmount(() => { root?.unmount(); root = null })
function setValue(value) { externalValue.value = String(value ?? ''); revision.value++; render() }
function focus() { host.value?.querySelector('textarea')?.focus() }
defineExpose({ setValue, focus })
</script>

<style>
/* The registry's theme is mapped to the surrounding workspace, including dark mode. */
.library-composer {
  --an-max-width: 100%;
  --an-border-radius: 16px;
  --an-background: var(--panel, #fff);
  --an-background-secondary: var(--panel-2, #f7f8f7);
  --an-background-tertiary: var(--panel-2, #f7f8f7);
  --an-foreground: var(--text, #24262a);
  --an-foreground-muted: var(--muted, #68706d);
  --an-foreground-subtle: var(--muted, #68706d);
  --an-border-color: var(--line, #e7e9e7);
  --an-primary-color: var(--accent, #24694e);
  --an-input-background: var(--panel, #fff);
  --an-input-border-color: var(--line, #e7e9e7);
  --an-input-color: var(--text, #24262a);
  --an-input-placeholder-color: var(--muted, #68706d);
  --an-input-focus-outline: var(--accent, #24694e);
  --an-send-button-bg: var(--accent, #24694e);
  --an-send-button-color: var(--bg, #fff);
  --an-tool-color: var(--text, #24262a);
  --an-tool-color-muted: var(--muted, #68706d);
  width: 100%;
  min-width: 0;
}
.library-composer-input { padding: 0; }
.library-composer textarea { display: block; min-height: 76px; max-height: 180px; font: inherit; font-size: 14px; line-height: 1.65; }
.library-composer textarea:disabled { opacity: .65; }
.library-composer button { font: inherit; }
.library-composer button:focus-visible { outline: 2px solid var(--an-primary-color); outline-offset: 3px; }
.library-composer .an-composer-surface { border: 0; box-shadow: none; transition: border-color .15s; }
.library-composer .an-composer-surface:focus-within { border-color: var(--an-primary-color); }
.library-composer textarea:focus-visible { outline: none; }
.library-composer .an-composer-toolbar { min-height: 48px; align-items: center; }
.library-composer .an-composer-left { flex: 1; }
.library-composer .an-model-trigger { max-width: 230px; min-width: 0; }
.library-composer .an-model-trigger>span:first-child { min-width: 0; }
.library-composer .an-model-popup { font-family: inherit; }
.library-composer .an-model-description { font-size: 11px; margin-top: 3px; line-height: 1.5; }
.library-composer .an-model-option[aria-pressed='true'] { background: var(--an-background-secondary); }
.library-composer .an-model-trigger svg,.library-composer .an-model-option svg { color: var(--an-foreground-muted); }
.library-connector-action { display: inline-flex; align-items: center; gap: 6px; min-height: 36px; padding: 0 9px; border: 0; border-radius: 8px; background: transparent; color: var(--an-foreground-muted); font-size: 12px !important; cursor: pointer; }
.library-connector-action:hover { background: var(--an-background-secondary); color: var(--an-foreground); }
[data-theme='dark'] .library-composer {
  --an-background: var(--panel);
  --an-background-secondary: var(--panel-2);
  --an-background-tertiary: var(--panel-2);
  --an-foreground: var(--text);
  --an-foreground-muted: var(--muted);
  --an-foreground-subtle: var(--muted);
  --an-border-color: var(--line);
  --an-primary-color: var(--accent);
  --an-input-background: var(--panel);
  --an-input-color: var(--text);
  --an-input-placeholder-color: var(--muted);
  --an-input-focus-outline: var(--accent);
  --an-send-button-bg: var(--accent);
  --an-send-button-color: var(--bg);
}
@media (max-width: 540px) {
  .library-composer textarea { font-size: 16px; }
  .library-composer .an-model-trigger { max-width: 170px; }
  .library-composer .an-composer-toolbar { gap: 6px; }
  .library-composer .an-composer-left { gap: 3px; }
  .library-connector-action { width: 36px; padding: 0; justify-content: center; flex-shrink: 0; }
  .library-connector-action>span { display: none; }
}
@media (max-width: 360px) { .library-composer .an-model-trigger { max-width: 125px; padding-inline: 6px; } }
@media (prefers-reduced-motion: reduce) { .library-composer *, .library-composer *::before, .library-composer *::after { animation: none !important; transition: none !important; } }
/* Keep the registry model picker outside the composer clipping edge. */
.ws .direct-composer-wrap { overflow: visible; }
.library-composer .library-add-trigger { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; flex-shrink: 0; padding: 0; border: 0; border-radius: 9px; background: transparent; color: var(--an-foreground-muted); cursor: pointer; }
.library-composer .library-add-trigger:hover, .library-composer .library-add-trigger[data-popup-open] { background: var(--an-background-secondary); color: var(--an-foreground); }
.library-composer .library-add-trigger:disabled { opacity: .4; cursor: default; }
.library-context-positioner { z-index: 90; }
.library-context-popup { width: 294px; max-width: calc(100vw - 28px); padding: 6px; border: 1px solid #e1e3ec; border-radius: 14px; color: #252638; background: #fff; box-shadow: 0 14px 42px rgb(38 34 65 / 14%); font-family: Inter, system-ui, sans-serif; outline: none; }
.library-context-popup[data-theme='dark'] { color: #f1eff8; background: #292d42; border-color: #454961; }
.library-context-item { display: flex; align-items: center; gap: 13px; width: 100%; min-height: 59px; padding: 10px 12px; border: 0; border-radius: 9px; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.library-context-item:hover,.library-context-item:focus-visible { background: #f4f3fa; outline: none; }
.library-context-popup[data-theme='dark'] .library-context-item:hover,.library-context-popup[data-theme='dark'] .library-context-item:focus-visible { background: #373b53; }
.library-context-item>svg { flex-shrink: 0; opacity: .75; }
.library-context-item span { min-width: 0; }
.library-context-item b { display: block; font-size: 13px; line-height: 20px; font-weight: 550; }
.library-context-item small { display: block; font-size: 11px; line-height: 18px; opacity: .65; }
.library-context-item:last-child { margin-top: 4px; border-top: 1px solid #e9e9f1; border-top-left-radius: 0; border-top-right-radius: 0; padding-top: 13px; }
.library-context-popup[data-theme='dark'] .library-context-item:last-child { border-top-color: #454961; }
</style>

<style>
.library-composer .library-model-trigger { display: inline-flex; align-items: center; gap: 6px; color: var(--an-foreground-muted); background: transparent; border: 0; border-radius: 8px; cursor: pointer; }
.library-model-trigger>span { min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.library-model-popup { display: flex; flex-direction: column; width: 338px; padding: 0; overflow: hidden; max-height: min(440px, var(--available-height, calc(100dvh - 32px))); }
.library-model-search { display: flex; align-items: center; gap: 9px; flex-shrink: 0; padding: 13px 15px; border-bottom: 1px solid #e6e7ef; color: #7b7e91; }
.library-model-search input { min-width: 0; width: 100%; border: 0; outline: none; background: transparent; color: inherit; font: inherit; font-size: 12px; }
.library-model-list { min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 5px 6px; }
.library-model-group { margin: 0; padding: 9px 11px 5px; font-size: 10px; line-height: 16px; color: #7b7e91; font-weight: 600; text-transform: capitalize; }
.library-model-option { display: flex; align-items: center; justify-content: space-between; gap: 13px; width: 100%; min-height: 54px; padding: 10px 11px; border: 0; border-radius: 8px; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.library-model-option>span { min-width: 0; }
.library-model-option b { display: block; font-size: 12px; line-height: 19px; font-weight: 550; }
.library-model-option small { display: block; margin-top: 3px; font-size: 11px; line-height: 16px; opacity: .65; overflow-wrap: anywhere; }
.library-model-option>svg { flex-shrink: 0; }
.library-model-option:hover,.library-model-option:focus-visible,.library-model-option[aria-checked='true'] { background: #f2f2f8; outline: none; }
.library-model-add { display: flex; align-items: center; gap: 9px; min-height: 45px; flex-shrink: 0; width: 100%; padding: 12px 16px; border: 0; border-top: 1px solid #e6e7ef; background: transparent; color: inherit; font: inherit; font-size: 12px; text-align: left; cursor: pointer; }
.library-model-add:hover,.library-model-add:focus-visible { background: #f2f2f8; outline: none; }
.library-model-empty { padding: 20px 12px; margin: 0; font-size: 12px; color: #7b7e91; }
.library-model-popup[data-theme='dark'] .library-model-search,.library-model-popup[data-theme='dark'] .library-model-add { border-color: #454961; }
.library-model-popup[data-theme='dark'] .library-model-search,.library-model-popup[data-theme='dark'] .library-model-group { color: #b9b9cf; }
.library-model-popup[data-theme='dark'] .library-model-option:hover,.library-model-popup[data-theme='dark'] .library-model-option:focus-visible,.library-model-popup[data-theme='dark'] .library-model-option[aria-checked='true'],.library-model-popup[data-theme='dark'] .library-model-add:hover,.library-model-popup[data-theme='dark'] .library-model-add:focus-visible { background: #393d56; }
</style>

<style>
.library-model-connect{font-size:11px;line-height:1.4;flex-shrink:0;padding:4px 8px;border:1px solid color-mix(in srgb,currentColor 18%,transparent);border-radius:6px;opacity:.8}
.library-model-side{display:inline-flex;align-items:center;gap:6px;flex-shrink:0}
.library-model-status{white-space:nowrap}
.library-model-status[data-tone='ok']{color:#1f7a4d;border-color:color-mix(in srgb,#1f7a4d 30%,transparent)}
.library-model-status[data-tone='bad']{color:#b42318;border-color:color-mix(in srgb,#b42318 35%,transparent);opacity:1}
.library-model-popup[data-theme='dark'] .library-model-status[data-tone='ok']{color:#7fd6a8}
.library-model-popup[data-theme='dark'] .library-model-status[data-tone='bad']{color:#ffa39a}
.library-model-alert{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;padding:10px 15px;border-bottom:1px solid #e6e7ef;font-size:12px;line-height:1.45}
.library-model-alert p{margin:0;color:#b42318}
.library-model-fallback{padding:5px 10px;border:1px solid currentColor;border-radius:7px;background:transparent;color:inherit;font:inherit;font-size:12px;font-weight:550;cursor:pointer}
.library-model-fallback:hover,.library-model-fallback:focus-visible{background:#f2f2f8;outline:none}
.library-model-popup[data-theme='dark'] .library-model-alert{border-color:#454961}
.library-model-popup[data-theme='dark'] .library-model-alert p{color:#ffa39a}
.library-model-popup[data-theme='dark'] .library-model-fallback:hover,.library-model-popup[data-theme='dark'] .library-model-fallback:focus-visible{background:#393d56}
</style>
