<script setup>
import { onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const emit = defineEmits(['recorded', 'error'])

const SAMPLE_RATES = [8000, 16000, 22050, 44100, 48000]

const recording = ref(false)
const elapsed = ref(0)
const level = ref(0)
const sampleRate = ref(16000)
const limitEnabled = ref(true)
const limitSeconds = ref(5)
const fileInput = ref(null)

let timer = null

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function startPolling() {
  stopPolling()
  timer = setInterval(async () => {
    try {
      const status = await api.recordStatus()
      elapsed.value = status.elapsed
      level.value = status.level
      if (!status.recording && recording.value) {
        await finish()
      }
    } catch (error) {
      emit('error', error.message)
    }
  }, 300)
}

async function start() {
  try {
    await api.startRecord({
      duration: limitEnabled.value ? Number(limitSeconds.value) : null,
      sampleRate: Number(sampleRate.value),
    })
    recording.value = true
    elapsed.value = 0
    level.value = 0
    startPolling()
  } catch (error) {
    emit('error', error.message)
  }
}

async function finish() {
  stopPolling()
  try {
    const meta = await api.stopRecord()
    recording.value = false
    elapsed.value = 0
    level.value = 0
    emit('recorded', meta)
  } catch (error) {
    recording.value = false
    emit('error', error.message)
  }
}

async function upload(event) {
  const file = event.target.files?.[0]
  if (!file) return
  try {
    const meta = await api.upload(file)
    emit('recorded', meta)
  } catch (error) {
    emit('error', error.message)
  } finally {
    event.target.value = ''
  }
}

// RMS 语音电平通常落在 0~0.3，放大后更适合作为视觉指示
const levelPercent = () => Math.min(100, Math.round(level.value * 320))

onUnmounted(stopPolling)
</script>

<template>
  <section class="panel">
    <h2 class="panel-title">
      采集
      <span v-if="recording" class="rec-dot">录音中 {{ elapsed.toFixed(1) }}s</span>
    </h2>

    <div class="row">
      <label>采样率</label>
      <select v-model.number="sampleRate" :disabled="recording">
        <option v-for="rate in SAMPLE_RATES" :key="rate" :value="rate">{{ rate }} Hz</option>
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
      <div class="meter-fill" :style="{ width: levelPercent() + '%' }"></div>
    </div>

    <div class="actions">
      <button v-if="!recording" class="primary" @click="start">开始录音</button>
      <button v-else class="danger" @click="finish">停止录音</button>
      <button :disabled="recording" @click="fileInput.click()">上传文件</button>
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

.check {
  display: flex;
  align-items: center;
  gap: 6px;
}

.meter {
  height: 8px;
  background: #12151c;
  border: 1px solid var(--border);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 12px;
}

.meter-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--teal), var(--accent));
  transition: width 0.12s linear;
}

.actions {
  display: flex;
  gap: 8px;
}

.rec-dot {
  font-size: 12px;
  color: var(--danger);
}
</style>
