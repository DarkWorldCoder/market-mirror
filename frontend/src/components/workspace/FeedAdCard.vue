<template>
  <article class="ad" :class="variant" :aria-label="`${styleLabel} feed ad: ${ad.name}, simulated`">
    <div class="ad-frame">
      <!-- vertical video style: caption over a tall media block -->
      <template v-if="variant === 'vertical'">
        <div class="ad-media tall" role="img" :aria-label="mediaLabel">
          <span class="ad-media-note">{{ mediaLabel }}</span>
          <div class="ad-overlay">
            <b>{{ ad.page || 'Brand' }} <span class="ad-sponsor">{{ sponsorWord }}</span></b>
            <p>{{ ad.text || ad.headline }}</p>
            <span v-if="ad.cta" class="ad-cta">{{ ad.cta }}</span>
          </div>
        </div>
      </template>
      <template v-else>
        <header class="ad-head">
          <span class="ad-avatar" aria-hidden="true">{{ initials }}</span>
          <div>
            <b>{{ ad.page || 'Brand' }}</b>
            <span>{{ sponsorWord }}</span>
          </div>
        </header>
        <p v-if="variant === 'pro' && ad.headline" class="ad-headline">{{ ad.headline }}</p>
        <p v-if="variant !== 'square' && ad.text" class="ad-text">{{ ad.text }}</p>
        <div class="ad-media" :class="{ square: variant === 'square' }" role="img" :aria-label="mediaLabel">
          <span class="ad-media-note">{{ mediaLabel }}</span>
        </div>
        <div v-if="variant !== 'square'" class="ad-link">
          <div><small>{{ host }}</small><b>{{ ad.headline || ad.name }}</b></div>
          <span v-if="ad.cta" class="ad-cta">{{ ad.cta }}</span>
        </div>
        <p v-else class="ad-caption"><b>{{ ad.page || 'Brand' }}</b> {{ ad.text || ad.headline }}</p>
      </template>
    </div>

    <section class="ad-result" aria-label="What the simulated people did">
      <p class="ad-result-title">
        <span>{{ styleLabel }} feed ad · {{ ad.name }}</span>
        <span class="ad-sim">Simulated</span>
      </p>
      <template v-if="ad.shown">
        <p class="ad-result-line">Shown to {{ ad.shown }} simulated {{ plural(ad.shown, { one: 'person', other: 'people' }) }}<template v-if="ad.expectedCtr != null"> · expected click-through {{ ad.expectedCtr }}%</template></p>
        <div class="ad-bar" aria-hidden="true">
          <span class="clicked" :style="{ flexGrow: ad.clicked }"></span><span class="stopped" :style="{ flexGrow: ad.stopped }"></span><span class="scrolled" :style="{ flexGrow: ad.scrolled }"></span><span class="hid" :style="{ flexGrow: ad.hid }"></span>
        </div>
        <ul class="ad-legend">
          <li><i class="clicked"></i>Clicked {{ ad.clicked }}</li>
          <li><i class="stopped"></i>Stopped, then scrolled on {{ ad.stopped }}</li>
          <li><i class="scrolled"></i>Scrolled past {{ ad.scrolled }}</li>
          <li><i class="hid"></i>Hid it {{ ad.hid }}</li>
        </ul>
        <ul v-if="ad.thoughts.length" class="ad-thoughts">
          <li v-for="(t, i) in ad.thoughts" :key="i"><b>{{ t.who }}</b><small>{{ [t.segment, t.did].filter(Boolean).join(' · ') }}</small><p>“{{ t.text }}”</p></li>
        </ul>
      </template>
      <p v-else class="ad-result-line">No saved feed sessions for this ad.</p>
    </section>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { platformStyle } from '../../workspace/socialPosts'
import { plural } from '../../workspace/plural.js'

const props = defineProps({ ad: { type: Object, required: true } })
// layout families only; no platform branding
const variant = computed(() => ({ facebook: 'social', instagram: 'square', linkedin: 'pro', tiktok: 'vertical', youtube: 'vertical' })[props.ad.platform] || 'social')
const styleLabel = computed(() => platformStyle(props.ad.platform))
const sponsorWord = computed(() => (variant.value === 'pro' ? 'Promoted' : 'Sponsored'))
const initials = computed(() => String(props.ad.page || 'B').split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase())
const host = computed(() => {
  try {
    return props.ad.link ? new URL(props.ad.link).host : ''
  } catch {
    return ''
  }
})
const mediaLabel = computed(() => (props.ad.media ? `${props.ad.format === 'video' ? 'Video' : 'Image'}: ${props.ad.media}` : `${props.ad.format || 'Image'} (no description saved)`))
</script>

<style scoped>
.ad { display: grid; grid-template-columns: minmax(0, 340px) minmax(0, 1fr); gap: 16px; padding: 14px; border: 1px solid var(--line); border-radius: 14px; background: var(--panel); min-width: 0; }
.ad-frame { border: 1px solid var(--line); border-radius: 12px; overflow: hidden; background: var(--panel); min-width: 0; align-self: start; }
.ad-head { display: flex; align-items: center; gap: 9px; padding: 10px 12px; }
.ad-head b { display: block; font-size: 13px; }
.ad-head span { display: block; font-size: 11.5px; color: var(--muted); }
.ad-avatar { width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; background: var(--accent); color: #fff; font-size: 12px; font-weight: 650; flex: none; }
.pro .ad-avatar { border-radius: 6px; }
.ad-headline { margin: 0 12px 4px; font-size: 14px; font-weight: 650; }
.ad-text { margin: 0 12px 10px; font-size: 13px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; }
.ad-media { position: relative; min-height: 150px; display: flex; align-items: flex-end; padding: 10px; background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 22%, var(--panel-2)), color-mix(in srgb, var(--warm) 18%, var(--panel-2))); }
.ad-media.square { aspect-ratio: 1 / 1; min-height: 0; }
.ad-media.tall { aspect-ratio: 9 / 14; min-height: 0; align-items: flex-end; padding: 0; background: linear-gradient(180deg, #1d2a33, #0f1418); color: #f2f2f2; }
.ad-media-note { font-size: 11.5px; line-height: 1.45; color: var(--text); background: color-mix(in srgb, var(--panel) 82%, transparent); padding: 6px 8px; border-radius: 8px; max-width: 100%; overflow-wrap: anywhere; }
.tall .ad-media-note { position: absolute; top: 10px; left: 10px; right: 10px; color: #f2f2f2; background: rgb(255 255 255 / 10%); }
.ad-overlay { padding: 12px; width: 100%; background: linear-gradient(0deg, rgb(0 0 0 / 70%), transparent); }
.ad-overlay b { font-size: 13px; }
.ad-overlay p { margin: 4px 0 8px; font-size: 12.5px; line-height: 1.45; overflow-wrap: anywhere; }
.ad-sponsor { font-weight: 400; opacity: 0.8; font-size: 11px; margin-left: 4px; }
.ad-link { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px; background: var(--panel-2); }
.ad-link small { display: block; font-size: 11px; color: var(--muted); text-transform: lowercase; }
.ad-link b { display: block; font-size: 13px; overflow-wrap: anywhere; }
.ad-cta { flex: none; display: inline-block; padding: 6px 12px; border-radius: 8px; background: var(--text); color: var(--panel); font-size: 12px; font-weight: 600; }
.tall .ad-cta { background: #f2f2f2; color: #111; }
.ad-caption { margin: 0; padding: 10px 12px; font-size: 13px; line-height: 1.5; overflow-wrap: anywhere; }
.ad-result { min-width: 0; }
.ad-result-title { display: flex; justify-content: space-between; gap: 8px; margin: 0 0 6px; font-size: 13px; font-weight: 650; }
.ad-sim { font-size: 10.5px; font-weight: 500; color: var(--warm); border: 1px solid color-mix(in srgb, var(--warm) 45%, var(--line)); border-radius: 999px; padding: 0 7px; height: fit-content; white-space: nowrap; }
.ad-result-line { margin: 0 0 8px; font-size: 12.5px; color: var(--muted); }
.ad-bar { display: flex; height: 10px; border-radius: 999px; overflow: hidden; background: var(--panel-2); }
.ad-bar span { min-width: 0; }
.clicked { background: var(--yes); } .stopped { background: var(--maybe); } .scrolled { background: color-mix(in srgb, var(--muted) 45%, transparent); } .hid { background: var(--no); }
.ad-legend { list-style: none; display: flex; flex-wrap: wrap; gap: 4px 12px; padding: 0; margin: 8px 0 0; font-size: 12px; color: var(--muted); }
.ad-legend li { display: inline-flex; align-items: center; gap: 5px; }
.ad-legend i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.ad-thoughts { list-style: none; padding: 0; margin: 12px 0 0; display: grid; gap: 8px; }
.ad-thoughts li { padding: 8px 10px; border-radius: 10px; background: var(--panel-2); font-size: 12.5px; }
.ad-thoughts small { margin-left: 6px; color: var(--muted); font-size: 11.5px; }
.ad-thoughts p { margin: 3px 0 0; line-height: 1.5; overflow-wrap: anywhere; }
@media (max-width: 760px) { .ad { grid-template-columns: 1fr; } .ad-frame { max-width: 360px; } }
</style>
