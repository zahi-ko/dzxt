<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import type { AudioMeta, DeviceInfo, RecordLevelMessage } from '../api'

const emit = defineEmits<{
  recorded: [meta: AudioMeta]
  error: [message: string]
}>()

const SAMPLE_RATES = [16000, 44100, 48000]
const CHANNEL_OPTIONS = [
  { value: 1, label: '单声道' },
  { value: 2, label: '立体声' },
]

const recording = ref(false)
const elapsed = ref(0)
const level = ref(0)
const peak = ref(0)
const sampleRate = ref(48000)
const channels = ref(1)
const devices = ref<DeviceInfo[]>([])
const deviceIndex = ref<number | null>(null)
const limitEnabled = ref(true)
const limitSeconds = ref(5)
const transport = ref<'idle' | 'ws' | 'poll'>('idle')
const fileInput = ref<HTMLInputElement | null>(null)

let timer: ReturnType<typeof setInterval> | null = null
let socket: WebSocket | null = null

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  if (transport.value === 'poll') transport.value = 'idle'
}

function startPolling() {
  if (timer) return
  transport.value = 'poll'
  timer = setInterval(async () => {
    try {
      const status = await api.recordStatus()
      elapsed.value = status.elapsed
      level.value = status.level
      if (!status.recording && recording.value) await finish()
    } catch (error) {
      emit('error', (error as Error).message)
    }
  }, 300)
}

function closeSocket() {
  if (socket) {
    socket.onclose = null
    socket.onerror = null
    socket.onmessage = null
    socket.onopen = null
    socket.close()
    socket = null
  }
  if (transport.value === 'ws') transport.value = 'idle'
}

// WebSocket 优先：连续电平比 300ms 轮询顺滑得多。
// 连不上（代理未升级、后端不支持）时自动退回轮询，功能不降级。
function openSocket() {
  closeSocket()
  let url = ''
  try {
    url = api.recordLevelSocketUrl()
    socket = new WebSocket(url)
  } catch {
    startPolling()
    return
  }

  socket.onopen = () => {
    transport.value = 'ws'
    stopPolling()
  }
  socket.onmessage = (event: MessageEvent<string>) => {
    try {
      const message = JSON.parse(event.data) as RecordLevelMessage
      transport.value = 'ws'
      elapsed.value = message.elapsed
      level.value = message.level
      peak.value = message.peak
      if (!message.recording && recording.value) void finish()
    } catch {
      // 非预期消息，忽略
    }
  }
  socket.onerror = () => {
    if (recording.value) startPolling()
  }
  socket.onclose = () => {
    socket = null
    if (recording.value) startPolling()
  }
}

async function loadDevices() {
  try {
    const result = await api.devices()
    devices.value = result.items
    // 默认保持 null = 「系统默认」选项；仅当用户上次明确选过设备时才恢复
    if (deviceIndex.value !== null && !devices.value.some((d) => d.index === deviceIndex.value)) {
      deviceIndex.value = null
    }
  } catch (error) {
    emit('error', (error as Error).message)
  }
}

async function start() {
  try {
    await api.startRecord({
      duration: limitEnabled.value ? Number(limitSeconds.value) : null,
      sampleRate: Number(sampleRate.value),
      channels: Number(channels.value),
      device: deviceIndex.value,
    })
    recording.value = true
    elapsed.value = 0
    level.value = 0
    peak.value = 0
    openSocket()
    startPolling() // 兜底：WS 连上后会被停止
  } catch (error) {
    recording.value = false
    emit('error', (error as Error).message)
  }
}

async function finish() {
  stopPolling()
  closeSocket()
  try {
    const meta = await api.stopRecord()
    recording.value = false
    elapsed.value = 0
    level.value = 0
    peak.value = 0
    emit('recorded', meta)
  } catch (error) {
    recording.value = false
    emit('error', (error as Error).message)
  }
}

async function upload(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  try {
    const meta = await api.upload(file)
    emit('recorded', meta)
  } catch (error) {
    emit('error', (error as Error).message)
  } finally {
    target.value = ''
  }
}

// RMS 语音电平通常落在 0~0.3，放大后更适合作为视觉指示
const levelPercent = computed(() => Math.min(100, Math.round(level.value * 320)))
const peakPercent = computed(() => Math.min(100, Math.round(peak.value * 320)))
const transportHint = computed(() => {
  if (!recording.value) return ''
  return transport.value === 'ws' ? '实时电平 · WebSocket' : '实时电平 · 轮询'
})

onMounted(loadDevices)
onUnmounted(() => {
  stopPolling()
  closeSocket()
})
</script>

<template>
  <section class="panel">
    <h2 class="panel-title">
      采集
      <span v-if="recording" class="rec-dot">录音中 {{ elapsed.toFixed(1) }}s</span>
    </h2>

    <div class="row">
      <label>设备</label>
      <select v-model="deviceIndex" :disabled="recording">
        <option :value="null">系统默认</option>
        <option v-for="device in devices" :key="device.index" :value="device.index">
          {{ device.name }}（{{ device.channels }}ch）
        </option>
      </select>
    </div>

    <div class="row">
      <label>采样率</label>
      <select v-model.number="sampleRate" :disabled="recording">
        <option v-for="rate in SAMPLE_RATES" :key="rate" :value="rate">{{ rate }} Hz</option>
      </select>
    </div>

    <div class="row">
      <label>声道</label>
      <select v-model.number="channels" :disabled="recording">
        <option v-for="option in CHANNEL_OPTIONS" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
    </div>

    <div class="row">
      <label class="check">
        <input v-model="limitEnabled" type="checkbox" :disabled="recording" />
        定时停止
      </label>
      <input
        v-if="limitEnabled"
        v-model.number="limitSeconds"
        type="number"
        min="1"
        max="300"
        :disabled="recording"
      />
    </div>

    <div class="meter">
      <div class="meter-fill" :style="{ width: levelPercent + '%' }"></div>
      <div class="meter-peak" :style="{ left: peakPercent + '%' }"></div>
    </div>
    <p class="hint meter-hint">
      RMS {{ level.toFixed(4) }} · 峰值 {{ peak.toFixed(4) }}
      <span v-if="transportHint" class="dim">{{ transportHint }}</span>
    </p>

    <div class="actions">
      <button v-if="!recording" class="primary record" @click="start">
        <span class="rec-icon" aria-hidden="true"></span>开始录音
      </button>
      <button v-else class="danger record recording" @click="finish">
        <span class="rec-icon stop" aria-hidden="true"></span>停止录音
      </button>
      <button :disabled="recording" @click="fileInput?.click()">上传文件</button>
      <input ref="fileInput" type="file" accept="audio/*" hidden @change="upload" />
    </div>
  </section>
</template>

<style scoped>
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.row label {
  flex: 0 0 56px;
}

.row select,
.row input[type='number'] {
  flex: 1 1 auto;
  min-width: 0;
}

.row input[type='number'] {
  max-width: 90px;
}

.check {
  display: flex;
  align-items: center;
  gap: 6px;
}

.meter {
  position: relative;
  height: 10px;
  background: var(--scope-bg);
  border: none;
  border-radius: 5px;
  overflow: hidden;
  margin-bottom: 6px;
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.4);
}

.meter-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--scope-wave), var(--accent));
  transition: width 0.08s linear;
}

.meter-peak {
  position: absolute;
  top: 0;
  width: 2px;
  height: 100%;
  background: var(--danger);
  box-shadow: 0 0 5px rgba(240, 112, 112, 0.8);
}

.meter-hint {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin: 0 0 12px;
}

.actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* 录音主按钮：内嵌状态圆点，录音时红点脉冲 */
.record {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.rec-icon {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #fff;
  flex: 0 0 auto;
}

.rec-icon.stop {
  border-radius: 2px;
  background: var(--danger);
}

.recording .rec-icon.stop {
  animation: rec-pulse 1.1s ease-in-out infinite;
}

@keyframes rec-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}

.rec-dot {
  font-size: 12px;
  color: var(--danger);
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.rec-dot::before {
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--danger);
  animation: rec-pulse 1.1s ease-in-out infinite;
}

.dim {
  color: var(--text-dim);
}
</style>
