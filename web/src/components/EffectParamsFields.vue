<script setup lang="ts">
import type { FormField, ParamValue } from '../api'
import { enumLabel } from '../api'

// 参数表单渲染器：输入来自后端 JSON Schema，因此新增效果/操作无需改前端。
// 单效果面板、效果链面板、加噪降噪面板共用，保证三处交互一致。
// 支持：枚举 → 下拉框；可空字段 → 允许留空（提交为 null，由后端取缺省）。
const props = withDefaults(
  defineProps<{
    fields: FormField[]
    modelValue: Record<string, ParamValue>
  }>(),
  {
    fields: () => [],
    modelValue: () => ({}),
  }
)

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, ParamValue>]
}>()

// 滑块步长取「区间 1%」附近的整齐值，避免出现 0.65 这类怪数字
const NICE_STEPS = [0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10]

function hasRange(field: FormField): boolean {
  return field.min !== undefined && field.max !== undefined && field.options === undefined
}

function step(field: FormField): number {
  if (field.type === 'integer') return 1
  const raw = ((field.max ?? 0) - (field.min ?? 0)) / 100
  return NICE_STEPS.find((item) => item >= raw) ?? 1
}

function update(key: string, value: ParamValue) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}

// 数字输入留空 → null，交给后端取缺省（仅可空字段会走到这里）
function updateNumber(field: FormField, raw: string) {
  if (raw.trim() === '') {
    update(field.key, null)
    return
  }
  const parsed = Number(raw)
  if (!Number.isFinite(parsed)) return
  update(field.key, field.type === 'integer' ? Math.round(parsed) : parsed)
}

function display(field: FormField): string {
  const value = props.modelValue[field.key]
  if (value === undefined || value === null || value === '') return '缺省'
  return String(value)
}
</script>

<template>
  <div v-for="field in fields" :key="field.key" class="field">
    <label>
      {{ field.label }}
      <span class="mono dim">{{ display(field) }}</span>
    </label>

    <input
      v-if="field.type === 'boolean'"
      :checked="Boolean(modelValue[field.key])"
      type="checkbox"
      @change="update(field.key, ($event.target as HTMLInputElement).checked)"
    />

    <select
      v-else-if="field.options"
      :value="String(modelValue[field.key] ?? '')"
      @change="update(field.key, ($event.target as HTMLSelectElement).value)"
    >
      <option v-for="option in field.options" :key="option" :value="option">
        {{ enumLabel(option) }}
      </option>
    </select>

    <template v-else-if="hasRange(field) && modelValue[field.key] !== null">
      <input
        :value="Number(modelValue[field.key] ?? field.min ?? 0)"
        type="range"
        :min="field.min"
        :max="field.max"
        :step="step(field)"
        @input="updateNumber(field, ($event.target as HTMLInputElement).value)"
      />
    </template>

    <input
      v-else
      :value="modelValue[field.key] ?? ''"
      type="number"
      :step="field.type === 'integer' ? 1 : 'any'"
      :min="field.min"
      :max="field.max"
      :placeholder="field.nullable ? '缺省（留空即由后端自适应）' : ''"
      @input="updateNumber(field, ($event.target as HTMLInputElement).value)"
    />

    <p v-if="field.description" class="hint">{{ field.description }}</p>
  </div>
</template>

<style scoped>
.field {
  margin-bottom: 12px;
}

.field label {
  display: block;
  margin-bottom: 4px;
}

.field .hint {
  margin: 4px 0 0;
}

.dim {
  color: var(--text-dim);
}
</style>
