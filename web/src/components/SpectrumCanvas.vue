<script setup>
import { onMounted, ref, watch } from 'vue'

const props = defineProps({
  freqs: { type: Array, default: () => [] },
  magnitudeDb: { type: Array, default: () => [] },
})

const canvas = ref(null)

function draw() {
  const el = canvas.value
  if (!el) return

  const width = el.clientWidth || 600
  const height = el.clientHeight || 150
  const dpr = window.devicePixelRatio || 1
  el.width = Math.round(width * dpr)
  el.height = Math.round(height * dpr)

  const ctx = el.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, width, height)

  ctx.fillStyle = '#12151c'
  ctx.fillRect(0, 0, width, height)

  const count = props.freqs.length
  if (count === 0) {
    ctx.fillStyle = '#5c6478'
    ctx.font = '13px system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('暂无频谱数据', width / 2, height / 2)
    return
  }

  // dB 动态范围裁剪到 [-90, 0]，低于下限的抬到下限，避免噪声底占满画面
  const floorDb = -90
  const ceilingDb = 0
  const toY = (db) => {
    const clamped = Math.max(floorDb, Math.min(ceilingDb, db))
    return height - ((clamped - floorDb) / (ceilingDb - floorDb)) * height
  }

  ctx.strokeStyle = '#232936'
  ctx.lineWidth = 1
  for (let i = 1; i < 4; i += 1) {
    const y = (height / 4) * i
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(width, y)
    ctx.stroke()
  }

  ctx.beginPath()
  ctx.moveTo(0, height)
  for (let i = 0; i < count; i += 1) {
    const x = (i / (count - 1)) * width
    ctx.lineTo(x, toY(props.magnitudeDb[i]))
  }
  ctx.lineTo(width, height)
  ctx.closePath()

  const gradient = ctx.createLinearGradient(0, 0, 0, height)
  gradient.addColorStop(0, 'rgba(45, 212, 191, 0.55)')
  gradient.addColorStop(1, 'rgba(45, 212, 191, 0.04)')
  ctx.fillStyle = gradient
  ctx.fill()

  ctx.strokeStyle = '#2dd4bf'
  ctx.lineWidth = 1.2
  ctx.beginPath()
  for (let i = 0; i < count; i += 1) {
    const x = (i / (count - 1)) * width
    const y = toY(props.magnitudeDb[i])
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  }
  ctx.stroke()

  ctx.fillStyle = '#5c6478'
  ctx.font = '12px system-ui, sans-serif'
  ctx.textAlign = 'left'
  ctx.fillText('0 Hz', 6, height - 6)
  ctx.textAlign = 'right'
  ctx.fillText(`${Math.round(props.freqs[count - 1])} Hz`, width - 6, height - 6)
}

onMounted(draw)
watch(() => [props.freqs, props.magnitudeDb], draw, { deep: true })
</script>

<template>
  <canvas ref="canvas" class="canvas"></canvas>
</template>

<style scoped>
.canvas {
  width: 100%;
  height: 150px;
  display: block;
  border-radius: 6px;
}
</style>
