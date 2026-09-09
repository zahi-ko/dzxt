<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import type { CloneRefMeta, CloneStatusResponse, CloneSynthesizeResponse } from '../api'

// 语音克隆面板（3.1）。
// 链路：本面板 → 主干 /api/clone → 适配层(9900) → GPT-SoVITS 引擎(9880)。
// 合成产物按句柄制入库，applied 事件交给 App 走统一的刷新+选中+试听流程。
const emit = defineEmits<{
  applied: [result: CloneSynthesizeResponse]
  error: [message: string]
}>()

const status = ref<CloneStatusResponse | null>(null)
const refs = ref<CloneRefMeta[]>([])
const selectedRefId = ref('')
const promptText = ref('')
const newText = ref('')
const uploadPrompt = ref('')
const busy = ref(false)
const uploading = ref(false)
const importing = ref(false)

// ---------- 合成参数（记忆式默认：改动即存 localStorage，下次沿用上一次的值） ----------

interface CloneParams {
  textLang: string
  promptLang: string
  speedFactor: number
  textSplitMethod: string
  batchSize: number
  fragmentInterval: number
  temperature: number
  topK: number
  topP: number
  repetitionPenalty: number
  seed: number
}

const PARAMS_KEY = 'dzxt.clone-params.v1'
const LAST_REF_KEY = 'dzxt.clone-last-ref.v1'

const DEFAULT_PARAMS: CloneParams = {
  textLang: 'zh',
  promptLang: 'zh',
  speedFactor: 1.0,
  textSplitMethod: 'cut5',
  batchSize: 1,
  fragmentInterval: 0.3,
  temperature: 1.0,
  topK: 15,
  topP: 1.0,
  repetitionPenalty: 1.35,
  seed: -1,
}

function loadParams(): CloneParams {
  try {
    const raw = localStorage.getItem(PARAMS_KEY)
    if (!raw) return { ...DEFAULT_PARAMS }
    return { ...DEFAULT_PARAMS, ...(JSON.parse(raw) as Partial<CloneParams>) }
  } catch {
    return { ...DEFAULT_PARAMS }
  }
}

const params = ref<CloneParams>(loadParams())

watch(
  params,
  (value) => {
    try {
      localStorage.setItem(PARAMS_KEY, JSON.stringify(value))
    } catch {
      /* 隐私模式等场景下不可写，静默降级为会话内记忆 */
    }
  },
  { deep: true },
)

function resetParams() {
  params.value = { ...DEFAULT_PARAMS }
}

const selectedRef = computed(
  () => refs.value.find((item) => item.ref_id === selectedRefId.value) ?? null
)

const statusClass = computed(() => {
  if (!status.value) return 'off'
  if (status.value.adapter_online && status.value.engine_online) return 'on'
  if (status.value.adapter_online) return 'partial'
  return 'off'
})

const statusText = computed(() => {
  if (!status.value) return '检测中…'
  if (status.value.adapter_online && status.value.engine_online) return '克隆引擎在线'
  if (status.value.adapter_online) return '适配层在线，引擎离线'
  return '克隆子服务离线'
})

const statusHint = computed(() => {
  if (!status.value) return ''
  if (!status.value.adapter_online) return status.value.adapter_detail
  if (!status.value.engine_online) return status.value.engine_detail
  return `参考音频 ${status.value.refs} 份`
})

async function refreshStatus() {
  try {
    status.value = await api.cloneStatus()
  } catch (error) {
    status.value = null
    emit('error', (error as Error).message)
  }
}

async function refreshRefs(selectFirst = false) {
  try {
    refs.value = (await api.cloneRefs()).items
    // 记忆式参考音：上次选中的还在列表里就继续选中
    const lastRef = localStorage.getItem(LAST_REF_KEY)
    if (!selectedRefId.value && lastRef && refs.value.some((item) => item.ref_id === lastRef)) {
      selectedRefId.value = lastRef
    } else if (selectFirst && refs.value.length && !selectedRefId.value) {
      selectedRefId.value = refs.value[0].ref_id
    }
  } catch (error) {
    emit('error', (error as Error).message)
  }
}

watch(selectedRefId, (value) => {
  if (value) {
    try {
      localStorage.setItem(LAST_REF_KEY, value)
    } catch {
      /* 同上，静默降级 */
    }
  }
  const record = selectedRef.value
  promptText.value = record?.prompt_text ?? ''
  // 导入的音色带预设合成文本：为空时自动填入，选完即可试听
  if (record?.sample_text && !newText.value.trim()) {
    newText.value = record.sample_text
  }
})

async function uploadRef(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploading.value = true
  try {
    const meta = await api.cloneUploadRef(file, uploadPrompt.value)
    uploadPrompt.value = ''
    await refreshRefs()
    selectedRefId.value = meta.ref_id
  } catch (error) {
    emit('error', (error as Error).message)
  } finally {
    uploading.value = false
  }
}

async function importClone(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  importing.value = true
  try {
    const meta = await api.cloneImportRef(file)
    await refreshRefs()
    selectedRefId.value = meta.ref_id
  } catch (error) {
    emit('error', (error as Error).message)
  } finally {
    importing.value = false
  }
}

async function exportClone() {
  if (!selectedRefId.value) return
  try {
    await api.cloneExportRef(selectedRefId.value)
  } catch (error) {
    emit('error', (error as Error).message)
  }
}

async function removeRef() {
  if (!selectedRefId.value) return
  try {
    await api.cloneDeleteRef(selectedRefId.value)
    selectedRefId.value = ''
    promptText.value = ''
    await refreshRefs()
  } catch (error) {
    emit('error', (error as Error).message)
  }
}

async function synthesize() {
  if (!selectedRefId.value || !newText.value.trim()) return
  busy.value = true
  try {
    const result = await api.cloneSynthesize({
      refId: selectedRefId.value,
      text: newText.value.trim(),
      promptText: promptText.value,
    })
    emit('applied', result)
  } catch (error) {
    emit('error', (error as Error).message)
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  refreshStatus()
  refreshRefs(true)
})
</script>

<template>
  <section class="panel">
    <h2 class="panel-title">
      语音克隆
      <button class="mini" @click="refreshStatus">刷新状态</button>
    </h2>

    <p class="status" :class="statusClass" :title="statusHint">{{ statusText }}</p>

    <div class="field">
      <label>参考音频（WAV，建议 5–10 秒清晰人声）</label>
      <select v-model="selectedRefId">
        <option value="" disabled>选择参考音频</option>
        <option v-for="item in refs" :key="item.ref_id" :value="item.ref_id">
          {{ item.filename }}（{{ item.duration.toFixed(1) }}s）
        </option>
      </select>
    </div>

    <div class="upload-row">
      <input type="file" accept="audio/*,.wav,.mp3,.flac,.ogg,.opus,.m4a,.aac,.wma,.webm,.aiff" @change="uploadRef" />
      <span v-if="uploading" class="hint">上传中…</span>
    </div>
    <p class="hint">支持 wav / mp3 / flac / ogg / opus / m4a / aac / wma / webm / aiff，上传后自动转为 wav</p>
    <div class="field">
      <label>新参考音的文本（可选，上传时一并提交）</label>
      <input v-model="uploadPrompt" type="text" placeholder="这段参考音频说了什么" />
    </div>

    <div class="field">
      <label>导入音色（.clone 文件，含参考音频与文本）</label>
      <div class="upload-row">
        <input type="file" accept=".clone" @change="importClone" />
        <span v-if="importing" class="hint">导入中…</span>
      </div>
    </div>

    <template v-if="selectedRef">
      <div class="field">
        <label>参考文本（参与音色与韵律对齐，强烈建议填写）</label>
        <textarea v-model="promptText" rows="2" placeholder="参考音频的文字内容"></textarea>
      </div>
      <div class="ref-actions">
        <button class="mini" @click="exportClone">导出音色 (.clone)</button>
        <button class="danger-text" @click="removeRef">删除此参考音频</button>
      </div>
    </template>

    <div class="field">
      <label>合成文本（500 字以内，过长建议分段）</label>
      <textarea v-model="newText" rows="3" placeholder="输入要让 TA 说的话"></textarea>
    </div>

    <details class="advanced">
      <summary>高级参数（改动自动记忆，下次沿用上一次的值）</summary>
      <div class="field">
        <label>合成文本语言（决定发音分支；auto 自动检测但偶有误判，语言确定时选具体值更稳）</label>
        <select v-model="params.textLang">
          <option value="zh">中文 zh</option>
          <option value="en">英文 en</option>
          <option value="ja">日文 ja</option>
          <option value="ko">韩文 ko</option>
          <option value="yue">粤语 yue</option>
          <option value="auto">自动检测 auto</option>
          <option value="all_zh">中英混合（英文按中音读）all_zh</option>
          <option value="all_ja">日英混合 all_ja</option>
        </select>
      </div>
      <div class="field">
        <label>参考文本语言（参考音频「说了什么」的语言，与实际不符会明显劣化克隆）</label>
        <select v-model="params.promptLang">
          <option value="zh">中文 zh</option>
          <option value="en">英文 en</option>
          <option value="ja">日文 ja</option>
          <option value="ko">韩文 ko</option>
          <option value="yue">粤语 yue</option>
          <option value="auto">自动检测 auto</option>
        </select>
      </div>
      <div class="field">
        <label>语速（1.0 为原速，0.6 慢速 – 1.65 快速，过快易丢字）</label>
        <input v-model.number="params.speedFactor" type="number" step="0.05" min="0.5" max="2" />
      </div>
      <div class="field">
        <label>文本切分（长文本切句策略，影响停顿节奏与长句稳定性）</label>
        <select v-model="params.textSplitMethod">
          <option value="cut0">不切（整段一次合成）</option>
          <option value="cut1">凑四句一切</option>
          <option value="cut2">凑五句一切</option>
          <option value="cut3">按标点符号切</option>
          <option value="cut4">按英文句号切</option>
          <option value="cut5">按标点切，无标点凑五句（默认）</option>
        </select>
      </div>
      <div class="field">
        <label>批大小（每次并行合成的句数，越大越快、越吃显存；仅填写参考文本时生效）</label>
        <input v-model.number="params.batchSize" type="number" step="1" min="1" max="64" />
      </div>
      <div class="field">
        <label>句间停顿（切句拼接处的静音秒数，调大更从容、调小更连贯）</label>
        <input v-model.number="params.fragmentInterval" type="number" step="0.05" min="0" max="2" />
      </div>
      <div class="field">
        <label>随机温度 temperature（越高音色越起伏随机、越低越平直；发音怪异时调低）</label>
        <input v-model.number="params.temperature" type="number" step="0.05" min="0.01" max="2" />
      </div>
      <div class="field">
        <label>top_k（每步只在概率前 K 个候选字里采样，越小越保守、越不易跳字）</label>
        <input v-model.number="params.topK" type="number" step="1" min="1" max="200" />
      </div>
      <div class="field">
        <label>top_p（累计概率截断阈值，越小越保守；与 top_k 调一个即可）</label>
        <input v-model.number="params.topP" type="number" step="0.01" min="0.01" max="1" />
      </div>
      <div class="field">
        <label>重复惩罚（抑制复读卡顿：过低会重复吐字，过高会急促吞字）</label>
        <input v-model.number="params.repetitionPenalty" type="number" step="0.05" min="1" max="10" />
      </div>
      <div class="field">
        <label>随机种子（-1 每次随机；固定后相同文本与参数可复现同一结果）</label>
        <input v-model.number="params.seed" type="number" step="1" min="-1" />
      </div>
      <button class="mini" @click="resetParams">恢复默认参数</button>
    </details>

    <button class="primary full" :disabled="busy || !selectedRefId || !newText.trim()" @click="synthesize">
      {{ busy ? '合成中…' : '开始克隆合成' }}
    </button>
    <p class="hint">合成结果会出现在左侧音频列表，可继续施加效果、导出。</p>
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

.status.partial {
  color: var(--warn);
}

.status.off {
  color: var(--danger);
}

.field {
  margin-bottom: 12px;
}

.field label {
  display: block;
  margin-bottom: 4px;
}

.upload-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.upload-row input[type='file'] {
  font-size: 12px;
  color: var(--text-dim);
  width: 100%;
}

.ref-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 12px;
}

.mini {
  font-size: 12px;
  padding: 3px 10px;
}

.danger-text {
  background: none;
  border: none;
  padding: 0;
  color: var(--danger);
  font-size: 12px;
  cursor: pointer;
}

.danger-text:hover {
  text-decoration: underline;
}

.full {
  width: 100%;
}
</style>
