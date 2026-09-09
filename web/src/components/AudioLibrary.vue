<script setup lang="ts">
import { api } from '../api'
import type { AudioMeta } from '../api'

defineProps<{
  items: AudioMeta[]
  selectedId: string
}>()

const emit = defineEmits<{
  select: [audioId: string]
  play: [audioId: string]
  removed: [audioId: string]
  error: [message: string]
}>()

function formatDuration(seconds: number) {
  return `${Number(seconds).toFixed(2)}s`
}

async function remove(audioId: string) {
  try {
    await api.remove(audioId)
    emit('removed', audioId)
  } catch (error) {
    emit('error', (error as Error).message)
  }
}

// 播放统一交给底部播放器：列表里只负责"选中并播放"，
// 避免出现两套播放器导致进度条与列表状态不同步。
function play(audioId: string) {
  emit('play', audioId)
}
</script>

<template>
  <section class="panel">
    <h2 class="panel-title">
      音频列表
      <span class="hint">{{ items.length }} 条</span>
    </h2>

    <p v-if="items.length === 0" class="hint">还没有音频</p>

    <ul v-else class="list">
      <li
        v-for="item in items"
        :key="item.audio_id"
        :class="{ active: item.audio_id === selectedId }"
        @click="emit('select', item.audio_id)"
      >
        <div class="head">
          <span class="name">{{ item.label || item.audio_id }}</span>
          <span class="mono dim">{{ formatDuration(item.duration) }}</span>
        </div>
        <div class="meta mono dim">{{ item.sample_rate }} Hz · {{ item.channels }} 声道</div>
        <div class="ops">
          <button class="mini" @click.stop="play(item.audio_id)">播放</button>
          <a class="mini link" :href="api.downloadUrl(item.audio_id)">下载</a>
          <button class="mini danger" @click.stop="remove(item.audio_id)">删除</button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 320px;
  overflow-y: auto;
}

li {
  padding: 8px 10px 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  background: var(--panel-2);
  position: relative;
  transition: border-color 0.15s, transform 0.1s;
}

li:hover {
  border-color: var(--border-strong);
  transform: translateY(-1px);
}

li.active {
  border-color: var(--accent);
  background: var(--accent-soft);
}

li.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 2px;
  background: var(--accent);
}

.head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta {
  font-size: 11px;
}

.dim {
  color: var(--text-dim);
}

.ops {
  display: flex;
  gap: 6px;
  margin-top: 6px;
}

button.mini,
a.mini {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
}

a.link {
  color: var(--text);
  text-decoration: none;
  border: 1px solid var(--border);
  background: var(--panel);
  line-height: 1.6;
}
</style>
