<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

// 后端把 dB 矩阵量化成 0-255 的一维数组下发（行优先 time × freq），
// 这里直接写进 ImageData 再按整数比例放大绘制，避免逐像素循环。
const props = withDefaults(
  defineProps<{
    frames: number
    bins: number
    data: number[]
    times?: number[]
    freqs?: number[]
  }>(),
  {
    frames: 0,
    bins: 0,
    data: () => [],
    times: () => [],
    freqs: () => [],
  }
)

const canvas = ref<HTMLCanvasElement | null>(null)

// 经典蓝→青→黄→红热力色标，低频到高频的能量一眼可辨
function colorMap(value: number): [number, number, number] {
  const t = value / 255
  if (t < 0.25) return [8, 12, 24 + Math.round(t * 4 * 60)]
  if (t < 0.5) return [8, Math.round((t - 0.25) * 4 * 180), 200]
  if (t < 0.75) return [Math.round((t - 0.5) * 4 * 255), 210, Math.round(200 - (t - 0.5) * 4 * 180)]
  return [255, Math.round(210 - (t - 0.75) * 4 * 150), 40]
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

  if (props.frames === 0 || props.bins === 0 || props.data.length === 0) {
    ctx.fillStyle = '#5c6478'
    ctx.font = '13px system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('暂无语谱图数据', width / 2, height / 2)
    return
  }

  const image = ctx.createImageData(props.frames, props.bins)
  for (let i = 0; i < props.frames * props.bins; i += 1) {
    const [r, g, b] = colorMap(props.data[i] ?? 0)
    const offset = i * 4
    image.data[offset] = r
    image.data[offset + 1] = g
    image.data[offset + 2] = b
    image.data[offset + 3] = 255
  }

  // 中间画布做整数放大，避免 ImageData 逐像素缩放产生的插值模糊
  const buffer = document.createElement('canvas')
  buffer.width = props.frames
  buffer.height = props.bins
  buffer.getContext('2d')?.putImageData(image, 0, 0)

  // 频率轴翻转：bin 0（低频）画在底部，符合语谱图惯例
  ctx.imageSmoothingEnabled = true
  ctx.save()
  ctx.translate(0, height)
  ctx.scale(1, -1)
  ctx.drawImage(buffer, 0, 0, props.frames, props.bins, 0, 0, width, height)
  ctx.restore()

  ctx.fillStyle = '#5c6478'
  ctx.font = '12px system-ui, sans-serif'
  ctx.textAlign = 'left'
  ctx.fillText('0 Hz', 6, height - 6)
  if (props.freqs.length) {
    ctx.textAlign = 'left'
    ctx.fillText(`${Math.round(props.freqs[props.freqs.length - 1])} Hz`, 6, 14)
  }
  if (props.times.length) {
    ctx.textAlign = 'right'
    ctx.fillText(`${props.times[props.times.length - 1].toFixed(2)}s`, width - 6, height - 6)
  }
}

onMounted(draw)
watch(() => [props.frames, props.bins, props.data], draw, { deep: true })
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
