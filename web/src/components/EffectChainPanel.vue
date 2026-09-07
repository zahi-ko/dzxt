<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, schemaToFields } from '../api'
import type { ApplyEffectResponse, EffectInfo } from '../api'
import EffectParamsFields from './EffectParamsFields.vue'

// 效果链：按顺序串起多个效果，一次请求完成，只产出一个新句柄。
// 每一步的参数表单同样来自后端 Schema，新增效果无需改动本组件。
const props = withDefaults(
  defineProps<{
    effects: EffectInfo[]
    audioId: string
  }>(),
  {
    effects: () => [],
    audioId: '',
  }
)

const emit = defineEmits<{
  applied: [result: ApplyEffectResponse]
  error: [message: string]
}>()

type ParamValue = number | boolean | string

interface ChainStep {
  effect: string
  params: Record<string, ParamValue>
}

const steps = ref<ChainStep[]>([])
const busy = ref(false)

function schemaOf(name: string): Record<string, unknown> {
  return props.effects.find((item) => item.name === name)?.params_schema ?? {}
}

function fieldsOf(step: ChainStep) {
  return schemaToFields(schemaOf(step.effect))
}

function defaultsFor(name: string): Record<string, ParamValue> {
  const next: Record<string, ParamValue> = {}
  for (const field of schemaToFields(schemaOf(name))) next[field.key] = field.value ?? 0
  return next
}

function addStep() {
  const name = props.effects[0]?.name
  if (!name) return
  steps.value.push({ effect: name, params: defaultsFor(name) })
}

function removeStep(index: number) {
  steps.value.splice(index, 1)
}

function changeEffect(index: number, name: string) {
  steps.value[index] = { effect: name, params: defaultsFor(name) }
}

// 效果清单变化（后端重启等）时，丢弃已不存在的步骤，避免提交无效链
watch(
  () => props.effects,
  (list) => {
    const names = new Set(list.map((item) => item.name))
    steps.value = steps.value.filter((step) => names.has(step.effect))
  }
)

const canApply = computed(() => props.audioId !== '' && steps.value.length > 0)

async function apply() {
  if (!canApply.value) return
  busy.value = true
  try {
    const result = await api.applyChain({
      audioId: props.audioId,
      steps: steps.value.map((step) => ({ effect: step.effect, params: { ...step.params } })),
      saveAsNew: true,
    })
    emit('applied', result)
  } catch (error) {
    emit('error', (error as Error).message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="panel">
    <h2 class="panel-title">
      效果链
      <button class="mini" :disabled="!audioId" @click="addStep">添加步骤</button>
    </h2>

    <p v-if="!audioId" class="hint">请先在左侧选择一段音频</p>

    <template v-else>
      <p v-if="steps.length === 0" class="hint">
        还没有步骤。点「添加步骤」把多个效果串起来一次执行。
      </p>

      <div v-for="(step, index) in steps" :key="index" class="step">
        <div class="step-head">
          <span class="index mono">#{{ index + 1 }}</span>
          <select
            :value="step.effect"
            @change="changeEffect(index, ($event.target as HTMLSelectElement).value)"
          >
            <option v-for="effect in effects" :key="effect.name" :value="effect.name">
              {{ effect.title }}
            </option>
          </select>
          <button class="mini danger" @click="removeStep(index)">删除</button>
        </div>
        <EffectParamsFields
          :fields="fieldsOf(step)"
          :model-value="step.params"
          @update:model-value="step.params = $event"
        />
      </div>

      <button class="primary full" :disabled="!canApply || busy" @click="apply">
        {{ busy ? '处理中…' : `执行 ${steps.length} 步` }}
      </button>
    </template>
  </section>
</template>

<style scoped>
.step {
  padding: 8px 10px;
  margin-bottom: 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel-2);
}

.step-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.step-head select {
  flex: 1 1 auto;
  min-width: 0;
}

.index {
  font-size: 12px;
  color: var(--text-dim);
}

.full {
  width: 100%;
}
</style>
