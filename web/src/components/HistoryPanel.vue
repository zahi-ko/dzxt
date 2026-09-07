<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from '../api'
import type { EffectHistoryResponse } from '../api'

// 处理历史即血统：后端在每个产物上记录了从源头起的全部步骤，
// 「撤销」就是跳回上一版句柄，不覆盖、不删除任何既有音频。
const props = withDefaults(
  defineProps<{
    audioId: string
    reloadToken?: number
  }>(),
  {
    audioId: '',
    reloadToken: 0,
  }
)

const emit = defineEmits<{
  navigate: [audioId: string]
  error: [message: string]
}>()

const history = ref<EffectHistoryResponse | null>(null)
const busy = ref(false)

function formatParams(params: Record<string, unknown>): string {
  const entries = Object.entries(params)
  if (entries.length === 0) return ''
  return entries
    .map(([key, value]) => {
      const text = typeof value === 'number' ? Number(value.toFixed(3)).toString() : String(value)
      return `${key}=${text}`
    })
    .join('，')
}

async function load() {
  if (!props.audioId) {
    history.value = null
    return
  }
  try {
    history.value = await api.history(props.audioId)
  } catch (error) {
    emit('error', (error as Error).message)
  }
}

async function undo() {
  if (!props.audioId) return
  busy.value = true
  try {
    const result = await api.undo(props.audioId)
    emit('navigate', result.audio_id)
  } catch (error) {
    emit('error', (error as Error).message)
  } finally {
    busy.value = false
  }
}

watch(() => [props.audioId, props.reloadToken], load, { immediate: true })
</script>

<template>
  <section class="panel">
    <h2 class="panel-title">
      处理历史
      <button class="mini" :disabled="!history || history.steps.length === 0 || busy" @click="undo">
        撤销一步
      </button>
    </h2>

    <p v-if="!audioId" class="hint">请先在左侧选择一段音频</p>
    <p v-else-if="!history" class="hint">加载中…</p>

    <template v-else>
      <ol class="chain">
        <li class="node root">
          <span class="title">原始音频</span>
          <button class="mini" :disabled="history.root_id === audioId" @click="emit('navigate', history.root_id)">
            跳到原始
          </button>
        </li>
        <li v-for="(step, index) in history.steps" :key="index" class="node">
          <span class="arrow">↓</span>
          <span class="title">{{ step.title }}</span>
          <span class="mono dim">{{ formatParams(step.params) }}</span>
        </li>
      </ol>
      <p v-if="history.steps.length === 0" class="hint">尚未施加任何效果</p>
    </template>
  </section>
</template>

<style scoped>
.chain {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.node {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  min-width: 0;
}

.node.root .title {
  color: var(--teal);
}

.title {
  flex: 0 0 auto;
}

.node .dim {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.arrow {
  color: var(--text-dim);
}
</style>
