<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

// 用 min/max 包络绘制波形：无论音频多长，数据量恒定为 points 个点，
// 视觉效果与逐采样绘制等价，但传输与渲染成本都低两个数量级。
//
// 交互：滚轮缩放（以指针为中心）· 拖动框选 · Shift+拖动平移 · 双击全览
const props = withDefaults(
  defineProps<{
    minimum: number[]
    maximum: number[]
    duration: number
    selection?: { start: number; end: number } | null
    playhead?: number
  }>(),
  {
    minimum: () => [],
    maximum: () => [],
    duration: 0,
    selection: null,
    playhead: -1,
  }
)

const emit = defineEmits<{
  'update:selection': [value: { start: number; end: number } | null]
  seek: [seconds: number]
}>()

const canvas = ref<HTMLCanvasElement | null>(null)
const viewStart = ref(0)
const viewEnd = ref(1)
const dragStart = ref<number | null>(null)
const dragCurrent = ref<number | null>(null)
const panning = ref(false)

const MIN_VIEW = 0.005 // 最多放大到全长的 0.5%

const visibleSelection = computed(() => {
  if (dragStart.value !== null && dragCurrent.value !== null) {
    const a = Math.min(dragStart.value, dragCurrent.value)
    const b = Math.max(dragStart.value, dragCurrent.value)
    return { start: a, end: b }
  }
  return props.selection
})

function resetView() {
  viewStart.value = 0
  viewEnd.value = 1
}

function zoom(factor: number, center = 0.5) {
  const span = Math.max(MIN_VIEW, (viewEnd.value - viewStart.value) * factor)
  if (span >= 1) {
    resetView()
    return
  }
  // 以 center（视图内归一化位置）为锚点，保证指针下的波形不跑位
  const anchor = viewStart.value + (viewEnd.value - viewStart.value) * center
  let start = anchor - span * center
  let end = start + span
  if (start < 0) {
    start = 0
    end = span
  }
  if (end > 1) {
    end = 1
    start = 1 - span
  }
  viewStart.value = start
  viewEnd.value = end
}

function toTime(clientX: number): number {
  const el = canvas.value
  if (!el) return 0
  const rect = el.getBoundingClientRect()
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  return (viewStart.value + (viewEnd.value - viewStart.value) * ratio) * props.duration
}

function toRatio(clientX: number): number {
  const el = canvas.value
  if (!el) return 0
  const rect = el.getBoundingClientRect()
  return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
}

function onWheel(event: WheelEvent) {
  if (props.minimum.length === 0) return
  event.preventDefault()
  zoom(event.deltaY > 0 ? 1.2 : 1 / 1.2, toRatio(event.clientX))
}

function onMouseDown(event: MouseEvent) {
  if (props.minimum.length === 0) return
  if (event.shiftKey) {
    panning.value = true
    return
  }
  dragStart.value = toTime(event.clientX)
  dragCurrent.value = dragStart.value
}

function onMouseMove(event: MouseEvent) {
  if (panning.value) {
    const span = viewEnd.value - viewStart.value
    const delta = -event.movementX * (span / (canvas.value?.clientWidth || 600))
    let start = viewStart.value + delta
    let end = viewEnd.value + delta
    if (start < 0) {
      start = 0
      end = span
    }
    if (end > 1) {
      end = 1
      start = 1 - span
    }
    viewStart.value = start
    viewEnd.value = end
    return
  }
  if (dragStart.value !== null) dragCurrent.value = toTime(event.clientX)
}

function onMouseUp(event: MouseEvent) {
  if (panning.value) {
    panning.value = false
    return
  }
  if (dragStart.value === null) return
  const end = toTime(event.clientX)
  const start = dragStart.value
  dragStart.value = null
  dragCurrent.value = null
  if (Math.abs(end - start) * 1000 < 20) {
    // 视为点击而非框选：触发定位
    emit('seek', end)
    return
  }
  emit('update:selection', {
    start: Math.min(start, end),
    end: Math.max(start, end),
  })
}

function draw() {
  const el = canvas.value
  if (!el) return

  const ctx = el.getContext('2d')
  if (!ctx) return

  const width = el.clientWidth || 600
  const height = el.clientHeight || 160
  const dpr = window.devicePixelRatio || 1
  el.width = Math.round(width * dpr)
  el.height = Math.round(height * dpr)

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, width, height)

  ctx.fillStyle = '#12151c'
  ctx.fillRect(0, 0, width, height)

  const mid = height / 2
  ctx.strokeStyle = '#232936'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(0, mid)
  ctx.lineTo(width, mid)
  ctx.stroke()

  const count = props.minimum.length
  if (count === 0) {
    ctx.fillStyle = '#5c6478'
    ctx.font = '13px system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('暂无音频，请先录音或上传文件', width / 2, mid - 8)
    return
  }

  const i0 = Math.max(0, Math.floor(viewStart.value * count))
  const i1 = Math.min(count, Math.max(i0 + 2, Math.ceil(viewEnd.value * count)))
  const visible = i1 - i0
  const xOf = (index: number) => ((index - i0) / Math.max(1, visible - 1)) * width

  // 选区高亮：先把时间换算成索引，再换算成像素
  const selection = visibleSelection.value
  if (selection && props.duration > 0) {
    const sIdx = (selection.start / props.duration) * count
    const eIdx = (selection.end / props.duration) * count
    const sx = Math.max(0, Math.min(width, ((sIdx - i0) / Math.max(1, visible - 1)) * width))
    const ex = Math.max(0, Math.min(width, ((eIdx - i0) / Math.max(1, visible - 1)) * width))
    ctx.fillStyle = 'rgba(76, 141, 255, 0.18)'
    ctx.fillRect(sx, 0, Math.max(1, ex - sx), height)
    ctx.strokeStyle = 'rgba(76, 141, 255, 0.55)'
    ctx.beginPath()
    ctx.moveTo(sx, 0)
    ctx.lineTo(sx, height)
    ctx.moveTo(ex, 0)
    ctx.lineTo(ex, height)
    ctx.stroke()
  }

  const amp = mid * 0.92
  ctx.strokeStyle = '#4c8dff'
  ctx.lineWidth = 1
  ctx.beginPath()
  for (let i = i0; i < i1; i += 1) {
    const x = xOf(i)
    const top = mid - props.maximum[i] * amp
    const bottom = mid - props.minimum[i] * amp
    ctx.moveTo(x, top)
    ctx.lineTo(x, Math.max(bottom, top + 0.6))
  }
  ctx.stroke()

  if (props.playhead >= 0 && props.duration > 0) {
    const pIdx = (props.playhead / props.duration) * count
    const px = ((pIdx - i0) / Math.max(1, visible - 1)) * width
    if (px >= 0 && px <= width) {
      ctx.strokeStyle = '#ef6b6b'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(px, 0)
      ctx.lineTo(px, height)
      ctx.stroke()
    }
  }

  // 时间刻度：按可视区间自适应，避免缩放到毫秒级时标签糊成一片
  ctx.fillStyle = '#5c6478'
  ctx.font = '11px system-ui, sans-serif'
  const spanSec = (viewEnd.value - viewStart.value) * props.duration
  for (let i = 0; i <= 4; i += 1) {
    const ratio = i / 4
    const seconds = (viewStart.value + (viewEnd.value - viewStart.value) * ratio) * props.duration
    const x = ratio * width
    ctx.strokeStyle = '#1c2130'
    ctx.beginPath()
    ctx.moveTo(x, height - 12)
    ctx.lineTo(x, height)
    ctx.stroke()
    ctx.textAlign = i === 0 ? 'left' : i === 4 ? 'right' : 'center'
    ctx.fillText(`${seconds.toFixed(spanSec < 1 ? 3 : 2)}s`, x, height - 2)
  }
}

onMounted(draw)
watch(
  () => [props.minimum, props.maximum, props.duration, props.selection, props.playhead, viewStart.value, viewEnd.value, dragCurrent.value],
  draw,
  { deep: true }
)

defineExpose({ zoom, resetView })
</script>

<template>
  <div class="wrap">
    <canvas
      ref="canvas"
      class="canvas"
      @wheel="onWheel"
      @mousedown="onMouseDown"
      @mousemove="onMouseMove"
      @mouseup="onMouseUp"
      @mouseleave="onMouseUp"
      @dblclick="resetView"
    ></canvas>
    <div class="toolbar">
      <button class="mini" title="放大" @click="zoom(1 / 1.5, 0.5)">＋</button>
      <button class="mini" title="缩小" @click="zoom(1.5, 0.5)">－</button>
      <button class="mini" title="全览" @click="resetView">全览</button>
      <button class="mini" :disabled="!selection" @click="emit('update:selection', null)">
        清除选区
      </button>
      <span class="hint">
        <template v-if="selection">
          选区 {{ selection.start.toFixed(2) }}s – {{ selection.end.toFixed(2) }}s（{{
            (selection.end - selection.start).toFixed(2)
          }}s）
        </template>
        <template v-else>滚轮缩放 · 拖动框选 · Shift 拖动平移 · 单击定位</template>
      </span>
    </div>
  </div>
</template>

<style scoped>
.wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.canvas {
  width: 100%;
  height: 160px;
  display: block;
  border-radius: 6px;
  cursor: crosshair;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
}

.toolbar .hint {
  margin: 0;
  margin-left: auto;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
</style>
