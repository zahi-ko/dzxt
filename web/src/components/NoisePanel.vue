<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api, schemaToFields } from '../api'
import type {
  AudioMeta,
  FormField,
  NoiseOperationInfo,
  NoiseProcessResponse,
  NoiseStatusResponse,
  ParamValue,
} from '../api'
import EffectParamsFields from './EffectParamsFields.vue'

// 语音加噪与降噪面板（3.3）。
// 链路：本面板 → 主干 /api/noise → 子服务 services/noise(9910)。
// 操作清单与参数表单全部来自后端，新增操作无需改本组件（与效果器注册表同思路）。
// 处理产物按句柄制入库，applied 事件交给 App 走统一的刷新+选中+试听流程。
const props = withDefaults(
  defineProps<{
    audioId: string
    items: AudioMeta[]
  }>(),
  {
    audioId: '',
    items: () => [],
  }
)

const emit = defineEmits<{
  applied: [result: NoiseProcessResponse]
  error: [message: string]
}>()

interface SnrRecord {
  key: number
  label: string
  value: number
}

const status = ref<NoiseStatusResponse | null>(null)
const operations = ref<NoiseOperationInfo[]>([])
const opName = ref('')
const params = ref<Record<string, ParamValue>>({})
const busy = ref(false)

// 闭环验证：基线（原始干净音频） vs 对比（处理后音频）
const snrClean = ref('')
const snrNoisy = ref('')
const snrBusy = ref(false)
const snrValue = ref<number | null>(null)
const records = ref<SnrRecord[]>([])
let recordSeq = 0

const currentOp = computed(
  () => operations.value.find((item) => item.name === opName.value) ?? null
)
const fields = computed<FormField[]>(() =>
  currentOp.value ? schemaToFields(currentOp.value.params_schema) : []
)

const currentLabel = computed(() => {
  const item = props.items.find((entry) => entry.audio_id === props.audioId)
  return item?.label || item?.audio_id || props.audioId
})

const statusClass = computed(() => {
  if (!status.value) return 'off'
  return status.value.online ? 'on' : 'off'
})

const statusText = computed(() => {
  if (!status.value) return '检测中…'
  return status.value.online ? '加噪降噪子服务在线' : '加噪降噪子服务离线'
})

const statusHint = computed(() => status.value?.detail ?? '')

function labelOf(audioId: string): string {
  const item = props.items.find((entry) => entry.audio_id === audioId)
  return item?.label || audioId.slice(0, 8)
}

function defaultsOf(list: FormField[]): Record<string, ParamValue> {
  const next: Record<string, ParamValue> = {}
  for (const field of list) {
    next[field.key] = field.value ?? (field.type === 'boolean' ? false : null)
  }
  return next
}

async function refreshStatus() {
  try {
    status.value = await api.noiseStatus()
  } catch (error) {
    status.value = { online: false, detail: (error as Error).message }
  }
}

async function loadOperations() {
  try {
    operations.value = (await api.noiseOperations()).items
    if (!operations.value.some((item) => item.name === opName.value)) {
      opName.value = operations.value[0]?.name ?? ''
    }
  } catch (error) {
    operations.value = []
    emit('error', (error as Error).message)
  }
}

// 切换操作即重置为该操作的 Schema 默认值
watch(opName, () => {
  params.value = defaultsOf(fields.value)
})

watch(fields, (list) => {
  // 首次拿到 Schema / 操作清单变化时补齐默认值
  if (Object.keys(params.value).length === 0) params.value = defaultsOf(list)
})

// 处理对象变化时，SNR 的「对比」侧自动跟随，基线留空待用户指定源头
watch(
  () => props.audioId,
  (value) => {
    snrNoisy.value = value
  },
  { immediate: true }
)

async function process() {
  if (!props.audioId || !opName.value) return
  busy.value = true
  try {
    const result = await api.noiseProcess({
      audioId: props.audioId,
      operation: opName.value,
      params: { ...params.value },
    })
    emit('applied', result)

    // 结果回流：对比侧指向产物，基线取血统源头（即原始音频），随后自动测一次
    snrNoisy.value = result.audio_id
    try {
      const history = await api.history(result.audio_id)
      if (history.root_id) snrClean.value = history.root_id
    } catch {
      /* 血统查询失败不影响主流程，用户可手动选基线 */
    }
    if (snrClean.value) await measure(currentOp.value?.title ?? opName.value)
  } catch (error) {
    emit('error', (error as Error).message)
  } finally {
    busy.value = false
  }
}

async function measure(label: string) {
  if (!snrClean.value || !snrNoisy.value) return
  snrBusy.value = true
  try {
    const response = await api.noiseSnr(snrClean.value, snrNoisy.value)
    snrValue.value = response.snr_db
    recordSeq += 1
    records.value.unshift({
      key: recordSeq,
      label: `${label} · ${labelOf(snrNoisy.value)}`,
      value: response.snr_db,
    })
  } catch (error) {
    emit('error', (error as Error).message)
  } finally {
    snrBusy.value = false
  }
}

function swapSnr() {
  const clean = snrClean.value
  snrClean.value = snrNoisy.value
  snrNoisy.value = clean
}

onMounted(() => {
  refreshStatus()
  loadOperations()
})
</script>

<template>
  <section class="panel">
    <h2 class="panel-title">
      语音加噪与降噪
      <button class="mini" @click="refreshStatus">刷新状态</button>
    </h2>

    <p class="status" :class="statusClass" :title="statusHint">{{ statusText }}</p>

    <p v-if="!audioId" class="hint">请先在左侧音频列表选择一条音频作为处理对象</p>

    <template v-else>
      <p class="target">
        处理对象 <strong>{{ currentLabel }}</strong>
      </p>

      <div class="op-tabs" role="tablist">
        <button
          v-for="operation in operations"
          :key="operation.name"
          role="tab"
          :aria-selected="opName === operation.name"
          :class="{ active: opName === operation.name }"
          @click="opName = operation.name"
        >
          {{ operation.title }}
        </button>
      </div>
      <p v-if="currentOp" class="hint">{{ currentOp.description }}</p>

      <EffectParamsFields v-model="params" :fields="fields" />

      <button class="primary full" :disabled="busy || !opName || !status?.online" @click="process">
        {{ busy ? '处理中…' : `执行${currentOp?.title ?? ''}` }}
      </button>
      <p class="hint">产物会出现在左侧音频列表并自动试听，可继续施加效果或导出。</p>

      <div class="snr-block">
        <h3>闭环验证 · 信噪比对比</h3>
        <p class="hint">同一音频「原始 → 加噪 → 降噪」后，对基线各算一次 SNR；数值越高说明噪声越少。</p>

        <div class="field">
          <label>基线（原始干净音频）</label>
          <select v-model="snrClean">
            <option value="" disabled>选择基线音频</option>
            <option v-for="item in items" :key="item.audio_id" :value="item.audio_id">
              {{ item.label || item.audio_id }}
            </option>
          </select>
        </div>

        <div class="field">
          <label>对比（处理后音频）</label>
          <select v-model="snrNoisy">
            <option value="" disabled>选择对比音频</option>
            <option v-for="item in items" :key="item.audio_id" :value="item.audio_id">
              {{ item.label || item.audio_id }}
            </option>
          </select>
        </div>

        <div class="snr-actions">
          <button
            class="mini"
            :disabled="!snrClean || !snrNoisy || snrBusy || !status?.online"
            @click="measure('手动测量')"
          >
            {{ snrBusy ? '测量中…' : '计算 SNR' }}
          </button>
          <button class="mini" :disabled="!snrClean || !snrNoisy" @click="swapSnr">对调</button>
        </div>

        <p v-if="snrValue !== null" class="snr-value">
          <span class="mono">{{ snrValue.toFixed(2) }}</span> dB
          <span class="hint">（{{ labelOf(snrClean) }} → {{ labelOf(snrNoisy) }}）</span>
        </p>

        <ul v-if="records.length" class="records">
          <li v-for="record in records" :key="record.key">
            <span class="record-label">{{ record.label }}</span>
            <span class="record-value mono" :class="{ good: record.value >= 10 }">
              {{ record.value.toFixed(2) }} dB
            </span>
          </li>
        </ul>
      </div>
    </template>
  </section>
</template>

<style scoped>
.status {
  margin: 0 0 12px;
  font-size: 12px;
}

.status.on {
  color: var(--teal);
}

.status.off {
  color: var(--danger);
}

.target {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--text-dim);
}

.target strong {
  color: var(--text);
  font-weight: 600;
}

/* 操作选择 · 下划线式标签（与主界面分析标签页同一语言） */
.op-tabs {
  display: flex;
  gap: 18px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 10px;
}

.op-tabs button {
  border: none;
  background: transparent;
  padding: 0 2px 8px;
  font-size: 13px;
  color: var(--text-dim);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  border-radius: 0;
}

.op-tabs button:hover:not(:disabled) {
  color: var(--text);
  background: transparent;
}

.op-tabs button.active {
  color: var(--accent);
  font-weight: 600;
  border-bottom-color: var(--accent);
}

.field {
  margin-bottom: 12px;
}

.field label {
  display: block;
  margin-bottom: 4px;
}

.mini {
  font-size: 12px;
  padding: 3px 10px;
}

.primary.full {
  width: 100%;
}

.snr-block {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

.snr-block h3 {
  margin: 0 0 6px;
  font-family: var(--font-serif);
  font-size: 14px;
  letter-spacing: 0.03em;
}

.snr-actions {
  display: flex;
  gap: 10px;
  margin-bottom: 10px;
}

.snr-value {
  margin: 0 0 10px;
  font-size: 15px;
}

.snr-value .mono {
  font-size: 22px;
  color: var(--accent);
}

.records {
  list-style: none;
  margin: 0;
  padding: 0;
  border-top: 1px dashed var(--border);
}

.records li {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--border);
  font-size: 12px;
}

.record-label {
  color: var(--text-dim);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.record-value {
  flex: 0 0 auto;
}

.record-value.good {
  color: var(--teal);
}
</style>
