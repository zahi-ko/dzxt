<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { api } from './api'
import type {
  ApplyEffectResponse,
  AudioMeta,
  AudioStatsResponse,
  CloneStatusResponse,
  CloneSynthesizeResponse,
  EffectInfo,
  EffectHistoryResponse,
  SpectrogramResponse,
  SpectrumResponse,
  WaveformResponse,
} from './api'
import AudioInfo from './components/AudioInfo.vue'
import AudioLibrary from './components/AudioLibrary.vue'
import ClonePanel from './components/ClonePanel.vue'
import EffectChainPanel from './components/EffectChainPanel.vue'
import EffectPanel from './components/EffectPanel.vue'
import HistoryPanel from './components/HistoryPanel.vue'
import PlayerBar from './components/PlayerBar.vue'
import RecorderCard from './components/RecorderCard.vue'
import SpectrogramCanvas from './components/SpectrogramCanvas.vue'
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
const spectrogram = ref<SpectrogramResponse>({
  audio_id: '',
  sample_rate: 0,
  times: [],
  freqs: [],
  frames: 0,
  bins: 0,
  data: [],
  floor_db: -80,
  ceiling_db: 0,
})
const stats = ref<AudioStatsResponse | null>(null)
const history = ref<EffectHistoryResponse | null>(null)
const selection = ref<{ start: number; end: number } | null>(null)
const playhead = ref(-1)
const player = ref<InstanceType<typeof PlayerBar> | null>(null)
const errorMessage = ref('')
const online = ref(false)

// 拓展功能：默认收起为卡片，点开才显示完整面板
const cloneOpen = ref(false)
const cloneStatus = ref<CloneStatusResponse | null>(null)
// 分析区标签页：频谱 / 语谱图共用一块面板，避免纵向堆叠过长
const analysisTab = ref<'spectrum' | 'spectrogram'>('spectrum')

function showError(message: string) {
  errorMessage.value = message
  setTimeout(() => {
    if (errorMessage.value === message) errorMessage.value = ''
  }, 6000)
}

const EMPTY_SPECTROGRAM: SpectrogramResponse = {
  audio_id: '',
  sample_rate: 0,
  times: [],
  freqs: [],
  frames: 0,
  bins: 0,
  data: [],
  floor_db: -80,
  ceiling_db: 0,
}

function clearAnalysis() {
  peaks.value = { audio_id: '', sample_rate: 0, duration: 0, points: 0, minimum: [], maximum: [] }
  spectrum.value = { audio_id: '', sample_rate: 0, freqs: [], magnitude_db: [] }
  spectrogram.value = { ...EMPTY_SPECTROGRAM }
  stats.value = null
  history.value = null
  selection.value = null
}

async function refreshAudios() {
  audios.value = (await api.listAudio()).items
}

async function refreshEffects() {
  effects.value = (await api.listEffects()).items
}

async function refreshCloneStatus() {
  try {
    cloneStatus.value = await api.cloneStatus()
  } catch {
    cloneStatus.value = null
  }
}

async function loadAnalysis(audioId: string) {
  const [envelope, freqData, statistics, spectro, effectHistory] = await Promise.all([
    api.peaks(audioId, 2000),
    api.spectrum(audioId, 2048),
    api.stats(audioId),
    api.spectrogram(audioId, 512, 480),
    api.history(audioId),
  ])
  peaks.value = envelope
  spectrum.value = freqData
  stats.value = statistics
  spectrogram.value = spectro
  history.value = effectHistory
  selection.value = null
}

async function selectAudio(audioId: string) {
  selectedId.value = audioId
  try {
    await loadAnalysis(audioId)
  } catch (error) {
    showError((error as Error).message)
  }
}

// 选区裁剪：把波形上框选的时间区间直接交给 trim 效果器，
// 复用效果链与处理历史，不必另开一套裁剪逻辑。
async function playFromLibrary(audioId: string) {
  await selectAudio(audioId)
  // 等 audio 元素的 src 绑定刷新后再播，否则播的还是上一条
  await nextTick()
  player.value?.play()
}

async function trimToSelection() {
  if (!selectedId.value || !selection.value) return
  try {
    const result = await api.applyEffect({
      audioId: selectedId.value,
      effect: 'trim',
      params: {
        start_sec: Number(selection.value.start.toFixed(4)),
        end_sec: Number(selection.value.end.toFixed(4)),
      },
      saveAsNew: true,
    })
    await handleApplied(result)
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

// 克隆产物与录音走同一刷新链路：入库句柄已由后端生成
async function handleCloned(result: CloneSynthesizeResponse) {
  cloneOpen.value = false
  await handleRecorded(result.meta)
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

// 拓展卡片上的克隆服务状态徽标（与 ClonePanel 内部状态各自拉取，互不耦合）
const cloneBadge = computed(() => {
  const status = cloneStatus.value
  if (!status) return { text: '未检测', cls: 'off' }
  if (status.adapter_online && status.engine_online) return { text: '在线', cls: 'on' }
  if (status.adapter_online) return { text: '引擎离线', cls: 'partial' }
  return { text: '离线', cls: 'off' }
})

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

  refreshCloneStatus()
})
</script>

<template>
  <div class="app">
    <header class="app-header">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">声</span>
        <div class="brand-text">
          <h1>语音处理系统</h1>
          <p class="brand-sub">Voice Processing Studio · 采集 · 处理 · 分析 · 播放</p>
        </div>
      </div>
      <div class="header-side">
        <span class="header-meta mono">STUDIO CONSOLE</span>
        <span class="status-pill" :class="{ on: online }">
          <span class="dot"></span>{{ statusText }}
        </span>
      </div>
    </header>

    <transition name="fade">
      <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
    </transition>

    <PlayerBar
      ref="player"
      class="player-bar"
      :audio-id="selectedId"
      :baseline-id="history?.root_id ?? ''"
      :duration="peaks.duration"
      @playhead="playhead = $event"
      @error="showError"
    />

    <main class="layout">
      <aside class="col side">
        <RecorderCard @recorded="handleRecorded" @error="showError" />
        <AudioLibrary
          :items="audios"
          :selected-id="selectedId"
          @select="selectAudio"
          @play="playFromLibrary"
          @removed="handleRemoved"
          @error="showError"
        />
      </aside>

      <section class="col main">
        <div class="panel">
          <h2 class="panel-title">
            波形
            <span v-if="selection" class="hint selection-hint mono">
              {{ selection.start.toFixed(2) }}s – {{ selection.end.toFixed(2) }}s
            </span>
            <button class="mini" :disabled="!selection" @click="trimToSelection">裁剪选区</button>
          </h2>
          <WaveformCanvas
            v-model:selection="selection"
            :minimum="peaks.minimum"
            :maximum="peaks.maximum"
            :duration="peaks.duration"
            :playhead="playhead"
            @seek="player?.seek($event)"
          />
          <AudioInfo :stats="stats" />
        </div>

        <div class="panel analysis">
          <div class="tabs" role="tablist">
            <button
              role="tab"
              :aria-selected="analysisTab === 'spectrum'"
              :class="{ active: analysisTab === 'spectrum' }"
              @click="analysisTab = 'spectrum'"
            >
              频谱（FFT 平均幅度谱）
            </button>
            <button
              role="tab"
              :aria-selected="analysisTab === 'spectrogram'"
              :class="{ active: analysisTab === 'spectrogram' }"
              @click="analysisTab = 'spectrogram'"
            >
              语谱图（STFT 时频图）
            </button>
          </div>
          <div class="tab-body">
            <SpectrumCanvas
              v-show="analysisTab === 'spectrum'"
              :freqs="spectrum.freqs"
              :magnitude-db="spectrum.magnitude_db"
            />
            <SpectrogramCanvas
              v-show="analysisTab === 'spectrogram'"
              :frames="spectrogram.frames"
              :bins="spectrogram.bins"
              :data="spectrogram.data"
              :times="spectrogram.times"
              :freqs="spectrogram.freqs"
            />
          </div>
        </div>
      </section>

      <aside class="col side">
        <EffectPanel
          :effects="effects"
          :audio-id="selectedId"
          @applied="handleApplied"
          @error="showError"
        />
        <EffectChainPanel
          :effects="effects"
          :audio-id="selectedId"
          @applied="handleApplied"
          @error="showError"
        />
        <HistoryPanel
          :audio-id="selectedId"
          :history="history"
          @navigate="selectAudio"
          @error="showError"
        />
      </aside>
    </main>

    <!-- 拓展功能：默认收起为卡片，点卡片展开完整面板，防止页面拥挤 -->
    <section class="extensions">
      <h2 class="section-title">拓展功能</h2>
      <div class="ext-grid">
        <button class="ext-card" @click="cloneOpen = true">
          <span class="ext-no" aria-hidden="true">01</span>
          <span class="ext-body">
            <span class="ext-name">语音克隆</span>
            <span class="ext-desc">上传参考音频，合成同款音色</span>
          </span>
          <span class="ext-badge" :class="cloneBadge.cls">{{ cloneBadge.text }}</span>
        </button>

        <button class="ext-card" disabled title="阶段三待开发">
          <span class="ext-no" aria-hidden="true">02</span>
          <span class="ext-body">
            <span class="ext-name">录音质量检测</span>
            <span class="ext-desc">音量 / 爆音 / 噪声综合评估</span>
          </span>
          <span class="ext-badge todo">开发中</span>
        </button>

        <button class="ext-card" disabled title="阶段三待开发">
          <span class="ext-no" aria-hidden="true">03</span>
          <span class="ext-body">
            <span class="ext-name">语音加噪与降噪</span>
            <span class="ext-desc">可调信噪比的闭环验证</span>
          </span>
          <span class="ext-badge todo">开发中</span>
        </button>
      </div>
    </section>

    <!-- 语音克隆抽屉 -->
    <transition name="drawer">
      <div v-if="cloneOpen" class="drawer-layer">
        <div class="drawer-mask" @click="cloneOpen = false"></div>
        <aside class="drawer" role="dialog" aria-label="语音克隆">
          <header class="drawer-head">
            <h2>语音克隆</h2>
            <button class="mini" aria-label="关闭" @click="cloneOpen = false">✕</button>
          </header>
          <div class="drawer-body">
            <ClonePanel @applied="handleCloned" @error="showError" />
          </div>
        </aside>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.app {
  max-width: 1440px;
  margin: 0 auto;
  padding: 26px 32px 56px;
}

/* ---------- 顶栏 · 编辑级刊头 ---------- */
.app-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  padding-bottom: 18px;
  margin-bottom: 16px;
  border-bottom: 2px solid var(--text);
}

.brand {
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand-mark {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  background: var(--text);
  color: var(--panel);
  font-family: var(--font-serif);
  font-size: 22px;
  line-height: 1;
  border-radius: 4px;
  flex: 0 0 auto;
}

.brand-text h1 {
  font-family: var(--font-serif);
  font-size: 30px;
  font-weight: 700;
  margin: 0;
  line-height: 1.15;
  letter-spacing: 0.04em;
}

.brand-sub {
  margin: 3px 0 0;
  font-size: 11px;
  color: var(--text-faint);
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.header-side {
  display: flex;
  align-items: center;
  gap: 14px;
}

.header-meta {
  font-size: 11px;
  color: var(--text-faint);
  letter-spacing: 0.22em;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  padding: 3px 12px;
  border-radius: 999px;
  border: 1px solid var(--danger);
  background: var(--danger-soft);
  color: var(--danger);
}

.status-pill .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.status-pill.on {
  border-color: var(--teal);
  background: var(--teal-soft);
  color: var(--teal);
}

/* ---------- 错误条 ---------- */
.error {
  margin: 0 0 14px;
  padding: 8px 12px;
  border: 1px solid var(--danger);
  border-left-width: 4px;
  border-radius: var(--radius-xs);
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 13px;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ---------- 三栏 ---------- */
.player-bar {
  margin-bottom: 18px;
}

.layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr) 300px;
  gap: 18px;
  align-items: start;
}

.col {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
}

/* ---------- 分析标签页 · 下划线式 ---------- */
.selection-hint {
  color: var(--accent);
  font-weight: 500;
}

.tabs {
  display: flex;
  gap: 22px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 12px;
}

.tabs button {
  border: none;
  background: transparent;
  padding: 0 2px 8px;
  font-size: 13px;
  color: var(--text-dim);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  border-radius: 0;
}

.tabs button:hover:not(:disabled) {
  color: var(--text);
  background: transparent;
}

.tabs button.active {
  color: var(--accent);
  font-weight: 600;
  border-bottom-color: var(--accent);
}

.tab-body {
  min-width: 0;
}

/* ---------- 拓展功能卡片 · 编号目录式 ---------- */
.extensions {
  margin-top: 26px;
  padding-top: 16px;
  border-top: 2px solid var(--text);
}

.section-title {
  font-family: var(--font-serif);
  font-size: 17px;
  font-weight: 700;
  margin: 0 0 12px;
  letter-spacing: 0.04em;
}

.ext-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}

.ext-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 18px;
  text-align: left;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-soft);
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.1s;
}

.ext-card:hover:not(:disabled) {
  border-color: var(--accent);
  box-shadow: 0 6px 20px rgba(201, 64, 28, 0.12);
  transform: translateY(-2px);
  color: var(--text);
  background: var(--panel);
}

.ext-card:disabled {
  opacity: 0.5;
}

.ext-no {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 30px;
  line-height: 1;
  color: var(--accent);
  flex: 0 0 auto;
  min-width: 44px;
}

.ext-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1 1 auto;
}

.ext-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.ext-desc {
  font-size: 12px;
  color: var(--text-dim);
}

.ext-badge {
  flex: 0 0 auto;
  font-size: 11px;
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid var(--danger);
  background: var(--danger-soft);
  color: var(--danger);
}

.ext-badge.on {
  border-color: var(--teal);
  background: var(--teal-soft);
  color: var(--teal);
}

.ext-badge.partial {
  border-color: var(--warn);
  background: var(--warn-soft);
  color: var(--warn);
}

.ext-badge.todo {
  border-color: var(--border-strong);
  background: var(--panel-2);
  color: var(--text-faint);
}

/* ---------- 抽屉 ---------- */
.drawer-layer {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  justify-content: flex-end;
}

.drawer-mask {
  position: absolute;
  inset: 0;
  background: rgba(37, 34, 28, 0.4);
}

.drawer {
  position: relative;
  width: min(400px, 92vw);
  height: 100%;
  background: var(--bg);
  border-left: 2px solid var(--text);
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
}

.drawer-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}

.drawer-head h2 {
  margin: 0;
  font-family: var(--font-serif);
  font-size: 19px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.drawer-body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 16px 18px 24px;
}

.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 0.2s;
}

.drawer-enter-active .drawer,
.drawer-leave-active .drawer {
  transition: transform 0.24s ease;
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}

.drawer-enter-from .drawer,
.drawer-leave-to .drawer {
  transform: translateX(40px);
}

/* ---------- 响应式 ---------- */
@media (max-width: 1100px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
