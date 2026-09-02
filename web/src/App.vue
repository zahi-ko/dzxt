<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from './api'
import type {
  ApplyEffectResponse,
  AudioMeta,
  AudioStatsResponse,
  EffectInfo,
  SpectrumResponse,
  WaveformResponse,
} from './api'
import AudioLibrary from './components/AudioLibrary.vue'
import EffectPanel from './components/EffectPanel.vue'
import RecorderCard from './components/RecorderCard.vue'
import SpectrumCanvas from './components/SpectrumCanvas.vue'
import WaveformCanvas from './components/WaveformCanvas.vue'

const audios = ref<AudioMeta[]>([])
const effects = ref<EffectInfo[]>([])
const selectedId = ref('')
const peaks = ref<WaveformResponse>({
  audio_id: '',
  sample_rate: 0,
  duration: 0,
  points: 0,
  minimum: [],
  maximum: [],
})
const spectrum = ref<SpectrumResponse>({
  audio_id: '',
  sample_rate: 0,
  freqs: [],
  magnitude_db: [],
})
const stats = ref<AudioStatsResponse | null>(null)
const errorMessage = ref('')
const online = ref(false)

function showError(message: string) {
  errorMessage.value = message
  setTimeout(() => {
    if (errorMessage.value === message) errorMessage.value = ''
  }, 6000)
}

function clearAnalysis() {
  peaks.value = { audio_id: '', sample_rate: 0, duration: 0, points: 0, minimum: [], maximum: [] }
  spectrum.value = { audio_id: '', sample_rate: 0, freqs: [], magnitude_db: [] }
  stats.value = null
}

async function refreshAudios() {
  audios.value = (await api.listAudio()).items
}

async function refreshEffects() {
  effects.value = (await api.listEffects()).items
}

async function loadAnalysis(audioId: string) {
  const [envelope, freqData, statistics] = await Promise.all([
    api.peaks(audioId, 2000),
    api.spectrum(audioId, 2048),
    api.stats(audioId),
  ])
  peaks.value = envelope
  spectrum.value = freqData
  stats.value = statistics
}

async function selectAudio(audioId: string) {
  selectedId.value = audioId
  try {
    await loadAnalysis(audioId)
  } catch (error) {
    showError((error as Error).message)
  }
}

async function handleRecorded(meta: AudioMeta) {
  try {
    await refreshAudios()
    await selectAudio(meta.audio_id)
  } catch (error) {
    showError((error as Error).message)
  }
}

async function handleApplied(result: ApplyEffectResponse) {
  try {
    await refreshAudios()
    await selectAudio(result.audio_id)
  } catch (error) {
    showError((error as Error).message)
  }
}

async function handleRemoved(audioId: string) {
  if (selectedId.value === audioId) {
    selectedId.value = ''
    clearAnalysis()
  }
  try {
    await refreshAudios()
  } catch (error) {
    showError((error as Error).message)
  }
}

const statusText = computed(() => (online.value ? '后端已连接' : '后端未连接'))

onMounted(async () => {
  try {
    await api.health()
    online.value = true
  } catch {
    online.value = false
  }

  try {
    await refreshEffects()
    await refreshAudios()
  } catch (error) {
    showError((error as Error).message)
  }
})
</script>

<template>
  <div class="app">
    <header>
      <h1>语音处理系统</h1>
      <span class="status" :class="{ on: online }">{{ statusText }}</span>
    </header>

    <p v-if="errorMessage" class="error">{{ errorMessage }}</p>

    <main class="layout">
      <aside class="col">
        <RecorderCard @recorded="handleRecorded" @error="showError" />
        <AudioLibrary
          :items="audios"
          :selected-id="selectedId"
          @select="selectAudio"
          @removed="handleRemoved"
          @error="showError"
        />
      </aside>

      <section class="col main">
        <div class="panel">
          <h2 class="panel-title">
            波形
            <span v-if="stats" class="hint mono">
              {{ stats.duration.toFixed(2) }}s · {{ stats.sample_rate }} Hz ·
              RMS {{ stats.rms.toFixed(4) }} · 峰值 {{ stats.peak.toFixed(4) }}
            </span>
          </h2>
          <WaveformCanvas
            :minimum="peaks.minimum"
            :maximum="peaks.maximum"
            :duration="peaks.duration"
          />
        </div>

        <div class="panel">
          <h2 class="panel-title">频谱</h2>
          <SpectrumCanvas :freqs="spectrum.freqs" :magnitude-db="spectrum.magnitude_db" />
        </div>
      </section>

      <aside class="col">
        <EffectPanel
          :effects="effects"
          :audio-id="selectedId"
          @applied="handleApplied"
          @error="showError"
        />
      </aside>
    </main>
  </div>
</template>

<style scoped>
.app {
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px 24px 40px;
}

header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 16px;
}

h1 {
  font-size: 18px;
  font-weight: 500;
  margin: 0;
}

.status {
  font-size: 12px;
  color: var(--danger);
}

.status.on {
  color: var(--teal);
}

.error {
  margin: 0 0 14px;
  padding: 8px 12px;
  border: 1px solid var(--danger);
  border-radius: 6px;
  background: rgba(239, 107, 107, 0.08);
  color: var(--danger);
  font-size: 13px;
}

.layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr) 300px;
  gap: 16px;
  align-items: start;
}

.col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

@media (max-width: 1100px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
