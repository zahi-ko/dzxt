<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api'

// 播放由浏览器承担：后端 sounddevice 拿不到播放位置，做不了进度条与暂停续播（ADR 0007）。
// A/B 对比用两个 audio 元素：切换时把播放位置搬过去，实现"同一时刻换版本"的听感对比。
const props = withDefaults(
  defineProps<{
    audioId: string
    baselineId?: string
    duration?: number
  }>(),
  {
    audioId: '',
    baselineId: '',
    duration: 0,
  }
)

const emit = defineEmits<{
  playhead: [seconds: number]
  error: [message: string]
}>()

const RATES = [0.5, 0.75, 1, 1.5, 2]

const audioA = ref<HTMLAudioElement | null>(null)
const audioB = ref<HTMLAudioElement | null>(null)
const playing = ref(false)
const currentTime = ref(0)
const totalTime = ref(0)
const rate = ref(1)
const compareOn = ref(false)
const activeSide = ref<'a' | 'b'>('a')

const canCompare = computed(
  () => props.baselineId !== '' && props.baselineId !== props.audioId
)
const streamUrl = computed(() => (props.audioId ? api.streamUrl(props.audioId) : ''))
const baselineUrl = computed(() => (props.baselineId ? api.streamUrl(props.baselineId) : ''))

function active(): HTMLAudioElement | null {
  return activeSide.value === 'a' ? audioA.value : audioB.value
}

function onTimeUpdate() {
  const el = active()
  if (!el) return
  currentTime.value = el.currentTime
  emit('playhead', el.currentTime)
}

function onLoaded() {
  const el = active()
  if (el && Number.isFinite(el.duration)) totalTime.value = el.duration
}

function onEnded() {
  playing.value = false
  currentTime.value = 0
  emit('playhead', -1)
}

function onError() {
  // 未选中音频时 src 属性不存在，理论上不会有 error；防御性兜底
  if (!props.audioId) return
  playing.value = false
  emit('error', '音频加载失败，请确认后端仍在运行')
}

async function play() {
  const el = active()
  if (!el) return
  try {
    await el.play()
    playing.value = true
  } catch (error) {
    emit('error', (error as Error).message)
  }
}

function pause() {
  audioA.value?.pause()
  audioB.value?.pause()
  playing.value = false
}

function stop() {
  pause()
  if (audioA.value) audioA.value.currentTime = 0
  if (audioB.value) audioB.value.currentTime = 0
  currentTime.value = 0
  emit('playhead', -1)
}

function seek(seconds: number) {
  const value = Math.max(0, seconds)
  currentTime.value = value
  if (audioA.value) audioA.value.currentTime = value
  if (audioB.value) audioB.value.currentTime = value
  emit('playhead', value)
}

function onSeek(event: Event) {
  seek(Number((event.target as HTMLInputElement).value))
}

// 切换 A/B：位置对齐后继续播放，否则听感对比不成立
async function switchSide(side: 'a' | 'b') {
  if (side === activeSide.value) return
  const from = active()
  const time = from?.currentTime ?? currentTime.value
  const wasPlaying = playing.value

  pause()
  activeSide.value = side
  const to = active()
  if (!to) return
  to.currentTime = time
  currentTime.value = time
  if (wasPlaying) await play()
}

function setRate(value: number) {
  rate.value = value
  if (audioA.value) audioA.value.playbackRate = value
  if (audioB.value) audioB.value.playbackRate = value
}

function format(seconds: number): string {
  if (!Number.isFinite(seconds)) return '0:00'
  const total = Math.floor(seconds)
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  return `${minutes}:${rest.toString().padStart(2, '0')}`
}

// 换音频：停止并回到 A 面
watch(
  () => props.audioId,
  () => {
    stop()
    activeSide.value = 'a'
    totalTime.value = props.duration || 0
  }
)

watch(
  () => props.duration,
  (value) => {
    if (value) totalTime.value = value
  }
)

watch(compareOn, (enabled) => {
  if (!enabled && activeSide.value === 'b') void switchSide('a')
})

defineExpose({ seek, play, pause, stop })
</script>

<template>
  <section class="player">
    <audio
      ref="audioA"
      :src="streamUrl || undefined"
      @timeupdate="onTimeUpdate"
      @loadedmetadata="onLoaded"
      @ended="onEnded"
      @error="onError"
    ></audio>
    <audio
      v-if="canCompare && compareOn"
      ref="audioB"
      :src="baselineUrl"
      @timeupdate="onTimeUpdate"
      @loadedmetadata="onLoaded"
      @ended="onEnded"
      @error="onError"
    ></audio>

    <div class="row">
      <button v-if="!playing" class="primary" :disabled="!audioId" @click="play">播放</button>
      <button v-else :disabled="!audioId" @click="pause">暂停</button>
      <button :disabled="!audioId" @click="stop">停止</button>

      <span class="time mono">{{ format(currentTime) }} / {{ format(totalTime) }}</span>

      <input
        class="seek"
        type="range"
        min="0"
        :max="totalTime || duration || 1"
        step="0.01"
        :value="currentTime"
        :disabled="!audioId"
        @input="onSeek"
      />

      <label class="rate">
        倍速
        <select :value="rate" @change="setRate(Number(($event.target as HTMLSelectElement).value))">
          <option v-for="value in RATES" :key="value" :value="value">{{ value }}×</option>
        </select>
      </label>

      <label v-if="canCompare" class="check" title="与处理前的原始音频对比">
        <input v-model="compareOn" type="checkbox" />
        A/B 对比
      </label>
      <div v-if="canCompare && compareOn" class="ab">
        <button class="mini" :class="{ on: activeSide === 'a' }" @click="switchSide('a')">
          A 当前
        </button>
        <button class="mini" :class="{ on: activeSide === 'b' }" @click="switchSide('b')">
          B 原始
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.player {
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent 40%), var(--panel);
  box-shadow: var(--shadow-soft);
}

.row {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* 播放键做主视觉：圆形渐变大按钮 */
.row > button.primary,
.row > button:nth-of-type(1) {
  min-width: 64px;
  text-align: center;
  font-weight: 600;
}

.time {
  font-size: 12px;
  color: var(--text-dim);
  white-space: nowrap;
  font-family: var(--font-mono);
}

.seek {
  flex: 1 1 auto;
  min-width: 80px;
}

.rate {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  white-space: nowrap;
}

.rate select {
  width: auto;
}

.check {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  white-space: nowrap;
}

.ab {
  display: flex;
  gap: 4px;
}

.ab .on {
  border-color: rgba(91, 140, 255, 0.55);
  background: var(--accent-soft);
  color: var(--accent);
}
</style>
