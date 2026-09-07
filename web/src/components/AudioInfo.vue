<script setup lang="ts">
import { computed } from 'vue'
import type { AudioStatsResponse } from '../api'

const props = withDefaults(defineProps<{ stats: AudioStatsResponse | null }>(), {
  stats: null,
})

function toDbfs(value: number): string {
  if (value <= 0) return '-∞'
  return `${(20 * Math.log10(value)).toFixed(1)}`
}

const items = computed(() => {
  const stats = props.stats
  if (!stats) return []
  return [
    { label: '时长', value: `${stats.duration.toFixed(3)} s` },
    { label: '采样率', value: `${stats.sample_rate} Hz` },
    { label: '声道', value: stats.channels === 1 ? '单声道' : `${stats.channels} 声道` },
    { label: '样本数', value: Math.round(stats.duration * stats.sample_rate).toLocaleString() },
    { label: 'RMS', value: `${stats.rms.toFixed(4)}（${toDbfs(stats.rms)} dBFS）` },
    { label: '峰值', value: `${stats.peak.toFixed(4)}（${toDbfs(stats.peak)} dBFS）` },
  ]
})
</script>

<template>
  <div v-if="stats" class="info">
    <div v-for="item in items" :key="item.label" class="cell">
      <span class="label">{{ item.label }}</span>
      <span class="value mono">{{ item.value }}</span>
    </div>
  </div>
  <p v-else class="hint">选择音频后显示基本信息</p>
</template>

<style scoped>
.info {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 8px;
}

.cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel-2);
}

.label {
  font-size: 11px;
  color: var(--text-dim);
}

.value {
  font-size: 13px;
}
</style>
