<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, schemaToFields } from '../api'
import type { ApplyEffectResponse, EffectInfo, FormField } from '../api'
import EffectParamsFields from './EffectParamsFields.vue'

// 这个面板没有任何硬编码的效果名。
// 效果清单与参数表单全部来自后端注册表的 JSON Schema，
// 因此新增效果时前端无需改动一行代码。
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

const selectedName = ref('')
const params = ref<Record<string, ParamValue>>({})
const saveAsNew = ref(true)
const busy = ref(false)

const current = computed(
  () => props.effects.find((item) => item.name === selectedName.value) ?? null
)
const fields = computed<FormField[]>(() =>
  current.value ? schemaToFields(current.value.params_schema) : []
)

watch(
  () => props.effects,
  (list) => {
    if (!list.some((item) => item.name === selectedName.value)) {
      selectedName.value = list[0]?.name ?? ''
    }
  },
  { immediate: true }
)

watch(
  selectedName,
  () => {
    const next: Record<string, ParamValue> = {}
    for (const field of fields.value) next[field.key] = field.value ?? 0
    params.value = next
  },
  { immediate: true }
)

async function apply() {
  if (!props.audioId || !selectedName.value) return
  busy.value = true
  try {
    const result = await api.applyEffect({
      audioId: props.audioId,
      effect: selectedName.value,
      params: { ...params.value },
      saveAsNew: saveAsNew.value,
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
    <h2 class="panel-title">处理</h2>

    <p v-if="!audioId" class="hint">请先在左侧选择一段音频</p>

    <template v-else>
      <div class="field">
        <label>效果器</label>
        <select v-model="selectedName">
          <option v-for="effect in effects" :key="effect.name" :value="effect.name">
            {{ effect.title }}
          </option>
        </select>
        <p v-if="current?.description" class="hint">{{ current.description }}</p>
      </div>

      <EffectParamsFields v-model="params" :fields="fields" />

      <div class="field">
        <label class="check">
          <input v-model="saveAsNew" type="checkbox" />
          生成新音频（不覆盖原音频）
        </label>
      </div>

      <button class="primary full" :disabled="busy" @click="apply">
        {{ busy ? '处理中…' : '应用效果' }}
      </button>
    </template>
  </section>
</template>

<style scoped>
.field {
  margin-bottom: 14px;
}

.field label {
  display: block;
  margin-bottom: 4px;
}

.field .hint {
  margin: 4px 0 0;
}

.check {
  display: flex;
  align-items: center;
  gap: 6px;
}

.dim {
  color: var(--text-dim);
}

.full {
  width: 100%;
}
</style>
