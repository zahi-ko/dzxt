// 前端唯一的后端耦合点。组件不直接调用 fetch。
// 约定：一律使用相对路径 /api，端口由 Vite 代理或后端托管屏蔽。
// 类型定义与 server/schemas.py 保持镜像，后端契约变更时必须同步更新。

const BASE = '/api'

// ---------- 类型定义（server/schemas.py 的镜像） ----------

export interface AudioMeta {
  audio_id: string
  sample_rate: number
  channels: number
  duration: number
  created_at: string
  label: string
}

export interface AudioListResponse {
  items: AudioMeta[]
}

export interface RecordStatusResponse {
  recording: boolean
  elapsed: number
  level: number
}

export interface EffectInfo {
  name: string
  title: string
  description: string
  params_schema: Record<string, unknown>
}

export interface EffectListResponse {
  items: EffectInfo[]
}

export interface ApplyEffectResponse {
  audio_id: string
  meta: AudioMeta
}

export interface WaveformResponse {
  audio_id: string
  sample_rate: number
  duration: number
  points: number
  minimum: number[]
  maximum: number[]
}

export interface SpectrumResponse {
  audio_id: string
  sample_rate: number
  freqs: number[]
  magnitude_db: number[]
}

export interface AudioStatsResponse {
  audio_id: string
  sample_rate: number
  channels: number
  duration: number
  rms: number
  peak: number
}

export interface HealthResponse {
  status: string
  effects: number
}

// ---------- 请求基础设施 ----------

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(BASE + path, options)
  } catch (error) {
    throw new Error(`无法连接后端服务：${(error as Error).message}`)
  }

  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: unknown }
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      // 响应体不是 JSON，沿用 statusText
    }
    throw new Error(detail)
  }

  if (response.status === 204) return null as T
  return (await response.json()) as T
}

function post<T>(path: string, payload?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload ?? {}),
  })
}

// ---------- API 集合 ----------

export const api = {
  health: () => request<HealthResponse>('/health'),

  listAudio: () => request<AudioListResponse>('/audio'),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<AudioMeta>('/audio/upload', { method: 'POST', body: form })
  },
  startRecord: (options: { duration?: number | null; sampleRate?: number } = {}) =>
    post<RecordStatusResponse>('/audio/record/start', {
      duration: options.duration ?? null,
      sample_rate: options.sampleRate ?? 16000,
    }),
  stopRecord: () => post<AudioMeta>('/audio/record/stop'),
  recordStatus: () => request<RecordStatusResponse>('/audio/record/status'),

  play: (audioId: string) => post<null>(`/audio/${audioId}/play`),
  stopPlay: () => post<null>('/audio/play/stop'),
  peaks: (audioId: string, points = 2000) =>
    request<WaveformResponse>(`/audio/${audioId}/peaks?points=${points}`),
  remove: (audioId: string) =>
    request<null>(`/audio/${audioId}`, { method: 'DELETE' }),
  downloadUrl: (audioId: string) => `${BASE}/audio/${audioId}/download`,

  listEffects: () => request<EffectListResponse>('/effects'),
  applyEffect: (options: {
    audioId: string
    effect: string
    params: Record<string, unknown>
    saveAsNew?: boolean
  }) =>
    post<ApplyEffectResponse>('/effects/apply', {
      audio_id: options.audioId,
      effect: options.effect,
      params: options.params,
      save_as_new: options.saveAsNew ?? true,
    }),

  spectrum: (audioId: string, nFft = 2048) =>
    post<SpectrumResponse>('/analysis/spectrum', { audio_id: audioId, n_fft: nFft }),
  stats: (audioId: string) => request<AudioStatsResponse>(`/analysis/${audioId}/stats`),
}

// ---------- JSON Schema → 表单字段 ----------

interface SchemaProperty {
  type?: string
  title?: string
  description?: string
  default?: number | boolean | string
  minimum?: number
  maximum?: number
}

export interface FormField {
  key: string
  label: string
  description: string
  type: string
  value: number | boolean | string | undefined
  min?: number
  max?: number
}

// 把后端下发的 JSON Schema 转成可渲染的表单字段描述
export function schemaToFields(schema: Record<string, unknown>): FormField[] {
  const properties = (schema.properties as Record<string, SchemaProperty> | undefined) ?? {}
  return Object.entries(properties).map(([key, spec]) => ({
    key,
    label: spec.title || key,
    description: spec.description || '',
    type: spec.type || 'number',
    value: spec.default,
    min: spec.minimum,
    max: spec.maximum,
  }))
}
