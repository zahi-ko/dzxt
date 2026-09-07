<script setup lang="ts">
import type { FormField } from '../api'

// 参数表单渲染器：输入来自后端 JSON Schema，因此新增效果无需改前端。
// 单效果面板与效果链面板共用，保证两处交互一致。
type ParamValue = number | boolean | string

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

function hasRange(field: FormField): boolean {
  return field.min !== undefined && field.max !== undefined
}

function step(field: FormField): number {
  return ((field.max ?? 0) - (field.min ?? 0)) / 100
}

function update(key: string, value: ParamValue) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>

<template>
  <div v-for="field in fields" :key="field.key" class="field">
    <label>
      {{ field.label }}
      <span class="mono dim">{{ modelValue[field.key] }}</span>
    </label>

    <input
      v-if="field.type === 'boolean'"
      :checked="Boolean(modelValue[field.key])"
      type="checkbox"
      @change="update(field.key, ($event.target as HTMLInputElement).checked)"
    />
    <template v-else-if="hasRange(field)">
      <input
        :value="Number(modelValue[field.key])"
        type="range"
        :min="field.min"
        :max="field.max"
        :step="step(field)"
        @input="update(field.key, Number(($event.target as HTMLInputElement).value))"
      />
    </template>
    <input
      v-else
      :value="Number(modelValue[field.key])"
      type="number"
      @input="update(field.key, Number(($event.target as HTMLInputElement).value))"
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
