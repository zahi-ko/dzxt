<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

// 用 min/max 包络绘制波形：无论音频多长，数据量恒定为 points 个点，
// 视觉效果与逐采样绘制等价，但传输与渲染成本都低两个数量级。
const props = withDefaults(
  defineProps<{
    minimum: number[]
    maximum: number[]
    duration: number
  }>(),
  {
    minimum: () => [],
    maximum: () => [],
    duration: 0,
  }
)

const canvas = ref<HTMLCanvasElement | null>(null)

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

  const amp = mid * 0.92
  ctx.strokeStyle = '#4c8dff'
  ctx.lineWidth = 1
  ctx.beginPath()
  for (let i = 0; i < count; i += 1) {
    const x = (i / Math.max(1, count - 1)) * width
    const top = mid - props.maximum[i] * amp
    const bottom = mid - props.minimum[i] * amp
    ctx.moveTo(x, top)
    ctx.lineTo(x, Math.max(bottom, top + 0.6))
  }
  ctx.stroke()

  ctx.fillStyle = '#5c6478'
  ctx.font = '12px system-ui, sans-serif'
  ctx.textAlign = 'left'
  ctx.fillText('0.00s', 6, height - 8)
  ctx.textAlign = 'right'
  ctx.fillText(`${props.duration.toFixed(2)}s`, width - 6, height - 8)
}

onMounted(draw)
watch(() => [props.minimum, props.maximum, props.duration], draw, { deep: true })
</script>

<template>
  <canvas ref="canvas" class="canvas"></canvas>
</template>

<style scoped>
.canvas {
  width: 100%;
  height: 160px;
  display: block;
  border-radius: 6px;
}
</style>
