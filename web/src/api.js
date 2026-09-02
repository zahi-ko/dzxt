// 前端唯一的后端耦合点。组件不直接调用 fetch。
// 约定：一律使用相对路径 /api，端口由 Vite 代理或后端托管屏蔽。

const BASE = '/api'

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(BASE + path, options)
  } catch (error) {
    throw new Error(`无法连接后端服务：${error.message}`)
  }

  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      // 响应体不是 JSON，沿用 statusText
    }
    throw new Error(detail)
  }

  if (response.status === 204) return null
  return response.json()
}

function post(path, payload) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload ?? {}),
  })
}

export const api = {
  health: () => request('/health'),

  listAudio: () => request('/audio'),
  upload: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/audio/upload', { method: 'POST', body: form })
  },
  startRecord: ({ duration = null, sampleRate = 16000 } = {}) =>
    post('/audio/record/start', { duration, sample_rate: sampleRate }),
  stopRecord: () => post('/audio/record/stop'),
  recordStatus: () => request('/audio/record/status'),

  play: (audioId) => post(`/audio/${audioId}/play`),
  stopPlay: () => post('/audio/play/stop'),
  peaks: (audioId, points = 2000) => request(`/audio/${audioId}/peaks?points=${points}`),
  remove: (audioId) => request(`/audio/${audioId}`, { method: 'DELETE' }),
  downloadUrl: (audioId) => `${BASE}/audio/${audioId}/download`,

  listEffects: () => request('/effects'),
  applyEffect: ({ audioId, effect, params, saveAsNew = true }) =>
    post('/effects/apply', {
      audio_id: audioId,
      effect,
      params,
      save_as_new: saveAsNew,
    }),

  spectrum: (audioId, nFft = 2048) => post('/analysis/spectrum', { audio_id: audioId, n_fft: nFft }),
  stats: (audioId) => request(`/analysis/${audioId}/stats`),
}

// 把后端下发的 JSON Schema 转成可渲染的表单字段描述
export function schemaToFields(schema) {
  const properties = schema?.properties ?? {}
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
