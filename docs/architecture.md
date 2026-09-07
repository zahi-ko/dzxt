# 架构设计说明书（AGENT 视角）

> 目标读者：接手本项目的 AI 代理 / 后续开发者。
> 目的：让一个新 session 读完本文件即可建立完整心智模型，足以独立完成维护、扩展与重构任务，无需重读全部源码。
>
> 与 `AGENT.md` 的关系：本文是 AGENT.md 的**机器可读补充**，讲清「代码现在的真实形态」与「为什么这么写」；AGENT.md 仍是项目唯一真相源，约定变更先改它。

---

## 0. 30 秒摘要

- 本系统是**语音处理系统课程项目**（语音处理系统设计与实现，第 14 组），产物为软件；当前阶段：**开题已完成，1.3 接口骨架已跑通**，进入阶段二功能开发。
- 技术骨架：**Python 3.11 + FastAPI + NumPy/SciPy + sounddevice/soundfile**（后端） · **Vue 3 + TypeScript + Vite**（前端）· **PyInstaller onedir**（打包）· **GPT-SoVITS 子服务**（语音克隆，独立 venv）。
- 架构支柱 = **三条铁律**：
  1. 内部音频一律 `np.ndarray[float32]`，值域 `[-1, 1]`，禁止传递 WAV/base64。
  2. API 只传 `audio_id` 句柄，波形永不出后端。
  3. 效果器必须为纯函数 + 通过注册表装饰器接入，新增效果不改任何既有文件。
- 三类交付能力：(a) 采集/处理/显示/播放 基础闭环（已可用）；(b) 三项拓展功能（语音克隆 · 录音质量检测 · 语音加噪与降噪）；(c) Windows 一键分发（`scripts/build_release.ps1` → `release/voice-system.zip`）。

---

## 1. 系统全景

### 1.1 部署形态

```text
+-------------------------+       +--------------------------+
| 浏览器 (Vue 3 SPA)      |       | 本机硬件                 |
| - RecorderCard          |       | - 麦克风（sounddevice）  |
| - AudioLibrary          |       | - 扬声器                 |
| - WaveformCanvas        |       | - NVIDIA GPU（仅克隆）   |
| - SpectrumCanvas        |       +--------------------------+
| - EffectPanel           |                  ▲
+-----------+-------------+                  │ HTTP (内部)
            | /api/* (相对路径)              │
            ▼                                ▼
+-------------------------+       +--------------------------+
| FastAPI 后端 (uvicorn)  | <---> | services/clone (GPT-SoVITS)|
| - /api/audio            |  HTTP | - Python 3.11 独立 venv   |
| - /api/effects          |  (待) | - PyTorch + CUDA          |
| - /api/analysis         |       | - 模型权重走下载脚本      |
| - /api/health           |       +--------------------------+
| - GET /  (托管 web/dist)|
+-----------+-------------+
            |
            ▼
+-------------------------+
| SessionStore（内存）    |  audio_id → np.ndarray[float32] + sr
| + 全局单例，线程安全    |
+-------------------------+
```

- **生产态**（打包后）：`app.exe` 同时托管后端 + 前端 `web/dist`，单一 8000 端口。
- **开发态**：前端由 Vite (5173) 起，所有 `/api/*` 代理到 8000；后端仅承担 API。
- **跨域**：仅开发态需要 CORS（已在 `server/main.py` 显式 allow `127.0.0.1:5173`）。

### 1.2 模块视图（自顶向下）

```text
AGENT.md, PLAN.md, docs/adr/*            真相源与决策记录
                │
                ▼
server/main.py                            FastAPI 入口 + 静态资源挂载
   ├── server/api/routers/audio.py        录音 / 文件 / 播放 / 删除 / 波形
   ├── server/api/routers/effects.py      效果清单 / 施加
   ├── server/api/routers/analysis.py     频谱 / 统计
   ├── server/api/deps.py                 require_entry（句柄 → 404）
   ├── server/schemas.py                  【契约层】Pydantic 模型
   ├── server/session_store.py            【句柄仓库】audio_id ↔ ndarray
   │
   ├── server/core/registry.py            效果器注册表（装饰器 + 自动 schema）
   ├── server/core/effects/basic.py       倒放 / 增益 / 倍速×2 / 归一化
   ├── server/core/analysis/spectrum.py   FFT 包络、波形 min/max、RMS、peak
   ├── server/core/io/device.py           Recorder / Player（sounddevice 封装）
   └── server/core/io/audio_file.py       WAV 读写（soundfile）
                │
                ▼
web/ (Vue 3 + TS + Vite)
   ├── web/src/api.ts                     【唯一后端耦合点】+ JSON-Schema → 表单
   ├── web/src/App.vue                    状态中枢
   └── web/src/components/*               RecorderCard / AudioLibrary /
                                          WaveformCanvas / SpectrumCanvas / EffectPanel
                │
                ▼
packaging/app.{py,spec} + scripts/build_release.ps1   PyInstaller onedir 流水线
services/clone/* (README 占位)             GPT-SoVITS 子服务，独立 venv（待实现）
```

---

## 2. 模块职责与边界（默认归属，软约束）

> 取自 `AGENT.md` §6。任何人可改任何文件，但改了别人负责的模块需在变更日志记录并知会。**唯一硬约束：`server/schemas.py` 改动必须全组同步。**

| 模块 | 职责 | 边界 / 不要做的事 |
|---|---|---|
| `server/schemas.py` | 全部 Pydantic 模型，HTTP 契约的唯一真相源 | **不要**放任何业务逻辑、工具函数 |
| `server/session_store.py` | `audio_id ↔ AudioEntry` 仓库，单例 + RLock | **不要**做 DSP；**不要**在外部捕获 `AudioEntry.data` 后长期持有引用（仓库 release 时内存复用） |
| `server/api/deps.py` | 公共依赖；目前仅 `require_entry` | **不要**在此写业务 |
| `server/api/routers/*.py` | HTTP 入参校验、错误码翻译、调用 Core / Store | **不要**直接做 DSP；**不要**绕过 `apply_effect` |
| `server/core/registry.py` | 效果器注册表 + 签名解析 + 输出规范化（dtype/dim/clip） | **不要**在此写具体效果算法 |
| `server/core/effects/*.py` | 一个效果一个文件，纯函数 | **不要**碰全局状态 / I/O / 改入参 / 返回非 float32 / 返回 1D/2D 之外的维度 |
| `server/core/analysis/*.py` | 频谱、包络、电平等纯函数 | **不要**碰 SessionStore；**不要**做任何 I/O |
| `server/core/io/*.py` | 录音 / 播放 / 文件读写 | **不要**在录音/播放路径上做效果处理（保持 I/O 与算法解耦） |
| `web/src/api.ts` | 后端耦合点；类型镜像 `schemas.py`；`request<T>` / `post<T>`；`schemaToFields` JSON-Schema → FormField | **不要**在 Vue 组件里直接 `fetch` / `axios`；**不要**硬编码后端端口 |
| `web/src/App.vue` | 全局状态中枢：选中音频、`peaks` / `spectrum` / `stats`、错误提示、在线状态 | **不要**在此放组件级 UI 状态 |
| `web/src/components/*` | 单一职责子组件，通过 `emit` 与 App 通信 | **不要**直接调 `fetch`；**不要**重复 `request<T>` 的错误处理（统一在 App） |
| `services/clone/` | GPT-SoVITS 子服务，独立 venv | **不要**导入主干代码；通过 HTTP 通信 |
| `packaging/` | PyInstaller 配置与打包入口 | **不要**在此写开发期逻辑 |
| `scripts/build_release.ps1` | 一键打包流水线 | 不要在开发期手动跑 |
| `docs/` | AGENT / PLAN / ADR / 每次 session 收工日志 | ADR 编号递增，不要覆盖 |

---

## 3. 核心组件与依赖

### 3.1 内部类型（铁律一 · 音频表示）

```text
type Audio = (np.ndarray, sample_rate: int)
  ndarray: float32, 值域 [-1, 1]
           单声道 → 1D shape (n,)
           多声道 → 2D shape (n, channels)
sample_rate: int, ∈ SUPPORTED_SAMPLE_RATES = (8000, 16000, 22050, 44100, 48000)
            默认 DEFAULT_SAMPLE_RATE = 48000（前端 RecorderCard 也默认 48000）
```

禁止形态：WAV bytes、base64 字符串、int16 数组、其它 dtype。`session_store.put` 与 `apply_effect.apply_effect` 是仅有的归一化入口（强制 `np.asarray(..., dtype=np.float32)`）。

### 3.2 SessionStore（铁律二 · 句柄制）

- 文件：`server/session_store.py`
- 数据：`AudioEntry { audio_id, data, sample_rate, created_at, label }`，存于 `_items: dict[str, AudioEntry]`，全局单例 `_STORE`，`RLock` 守护。
- 接口：`put(data, sr, label)` → entry；`get(audio_id)` → entry（缺失抛 KeyError）；`list()` → 按 created_at 升序；`delete(id)`；`replace(id, data, sr)`。
- 视图投影：`AudioEntry.to_meta()` → `AudioMeta`（仅元数据，不含波形），HTTP 出口统一用 meta。
- 派生属性：`channels = 1 if data.ndim == 1 else data.shape[1]`；`duration = data.shape[0] / sr`。
- **扩展点**：需要持久化时把 `SessionStore` 替换为磁盘 / Redis 实现即可，对外接口稳定。

### 3.3 效果器注册表（铁律三 · 扩展机制）

- 文件：`server/core/registry.py`
- 装饰器：`@register_effect(name, title, description="")`；用 `typing.get_type_hints` 解析第三个参数（`params`）的类型注解，因此效果文件可使用 `from __future__ import annotations`（自动求值注解）。
- 入口：`apply_effect(name, x, sr, params)` 负责 (a) 取注册项 (b) `model_validate(params)` (c) 转 float32 (d) 维度校验 (e) `np.clip(-1, 1)`。
- **自动暴露**：`EffectInfo.params_schema = params_model.model_json_schema()` 经 `GET /api/effects` 下发，前端用 `schemaToFields` 渲染表单 → 新增效果零前端改动。
- **注册触发**：在 `server/main.py` 顶部 `import server.core.effects`；新增效果文件后必须在 `server/core/effects/__init__.py` 加一行 import，装饰器才会执行。

#### 已注册效果器（`server/core/effects/basic.py`）

| name | title | params | 实现要点 |
|---|---|---|---|
| `reverse` | 倒放 | `EmptyParams` | `x[::-1]`，`np.ascontiguousarray` |
| `gain` | 音量增益 | `GainParams{db: float ∈[-60,24]}` | `10^(db/20)` 线性缩放；输出由 `apply_effect` 自动限幅 |
| `tempo_resample` | 倍速（变调） | `TempoParams{speed: float ∈[0.25,4]}` | `scipy.signal.resample_poly(x, 100, round(100*speed), axis=0)`；`|speed-1|<1e-3` 直通 |
| `tempo_ola` | 倍速（不变调） | 同上 | Hanning 帧 50ms，50% overlap OLA：`synthesis_hop = round(analysis_hop / speed)`；最后除以窗累积权重 |
| `normalize` | 峰值归一化 | `NormalizeParams{peak_db ∈[-24,0]}` | `x * (10^(peak_db/20) / peak)`，peak≈0 时直通 |

### 3.4 分析层（`server/core/analysis/spectrum.py`）

- `to_mono(x)` — 多声道取均值；纯函数。
- `average_spectrum(x, sr, n_fft=1024)` → `(freqs, magnitude_db)`：
  - 多声道先 to_mono；不足 n_fft 零填充；`hop = n_fft // 2`，Hanning 窗；
  - 用 `np.lib.stride_tricks.sliding_window_view` 取帧；`np.fft.rfft` → 平均功率 → 10·log10。
  - 返回长度 `n_fft//2+1`。
- `waveform_envelope(x, points=2000)` → `(min_list, max_list)`：
  - 等长段切分（`np.linspace` 边），输出点数恒定，前端画波形无需原始采样点。
- `rms_level(x)` / `peak_level(x)` — `to_mono` 后计算；空数组返回 0。

### 3.5 I/O 层（`server/core/io/`）

`audio_file.py`：
- `load_audio(payload: bytes) -> (np.ndarray[float32], sr)` — `soundfile.read(BytesIO, dtype="float32", always_2d=False)`。
- `dump_audio(data, sr, subtype="PCM_16") -> bytes` — `soundfile.write(BytesIO, ..., format="WAV")`。

`device.py`：
- `Recorder`（全局单例 `_RECORDER`）：
  - 状态：`recording`（`self._stream is not None`）、`elapsed`、`level`、内部 `_chunks`、`_timer`（定时停止）、`_auto_stopped` 标志。
  - `start(sample_rate, channels=1, duration=None)`：
    - 校验 `sample_rate ∈ SUPPORTED_SAMPLE_RATES`，否则抛 `ValueError`；已在录抛 `RuntimeError`。
    - `sd.InputStream(samplerate, channels, dtype="float32", blocksize=0, latency="low", callback=self._on_data)` —— `blocksize=0` 交给 PortAudio 自适应；`latency="low"` 降低延迟。
    - 若 `duration` 非 None：`threading.Timer(duration, self._auto_stop)`，`daemon=True`。
  - `_auto_stop`：到点关闭流但**保留 chunks**，等前端来取 `stop()`（避免自动停止丢数据的历史 bug）。
  - `_on_data`：锁内 `indata.copy()` 入 chunks；`self._level = float(sqrt(mean(indata**2)))` 暴露给前端。
  - `stop()`：若 `_auto_stopped` 直接 `_collect()`；否则关闭流 + `_collect()`；单声道返回 `(n,)`，多声道 `(n, channels)`。
- `Player`（全局单例 `_PLAYER`）：薄封装 `sd.play` / `sd.stop`，非阻塞。
- 模块导出：`get_recorder()` / `get_player()`。

### 3.6 API 路由层（`server/api/routers/`）

| 方法 | 路径 | 实现位置 | 说明 |
|---|---|---|---|
| GET | `/api/health` | `main.py` | `{status:"ok", effects:N}` |
| GET | `/api/audio` | `audio.py` | 列出全部 `AudioMeta` |
| POST | `/api/audio/upload` | `audio.py` | multipart `file` → `load_audio` → store.put；解码失败 415，空文件 400 |
| POST | `/api/audio/record/start` | `audio.py` | `Recorder.start(...)`；状态码 400/409 |
| GET | `/api/audio/record/status` | `audio.py` | 当前 recording / elapsed / level（前端 300ms 轮询） |
| POST | `/api/audio/record/stop` | `audio.py` | 取出数据 → store.put；空数据 422 |
| GET | `/api/audio/{id}/peaks?points=N` | `audio.py` | `waveform_envelope(data, N)` → `WaveformResponse`；`points ∈ [100,20000]` 默认 2000 |
| POST | `/api/audio/{id}/play` | `audio.py` | 204；调用 `Player.play` |
| POST | `/api/audio/play/stop` | `audio.py` | 204 |
| GET | `/api/audio/{id}/download` | `audio.py` | `dump_audio` → `audio/wav`，`Content-Disposition: attachment; filename="{id}.wav"` |
| DELETE | `/api/audio/{id}` | `audio.py` | 204；`require_entry` + `store.delete` |
| GET | `/api/effects` | `effects.py` | `list_effects()` → `EffectListResponse`（含 params_schema） |
| POST | `/api/effects/apply` | `effects.py` | `apply_effect(name, x, sr, params)` → 按 `save_as_new` 决定 `store.put` / `store.replace`；label 自动追加 ` → {title}`；效果名 404，参数 422 |
| POST | `/api/analysis/spectrum` | `analysis.py` | `SpectrumRequest{audio_id, n_fft ∈[128,8192]}` → 平均幅度谱 |
| GET | `/api/analysis/{id}/stats` | `analysis.py` | `rms_level` + `peak_level` |

错误约定：`HTTPException(status, detail=...)`；FastAPI 自动产出 `{"detail": ...}` JSON。`require_entry` 统一把 `KeyError` 翻 404。

### 3.7 服务入口（`server/main.py`）

- 创建 FastAPI app `title="语音处理系统"`，全局 `404: ErrorResponse`。
- CORS：仅 `http(s)://127.0.0.1:5173` 与 `http(s)://localhost:5173`。
- 顺序：`import server.core.effects`（触发注册） → include routers → `/api/health`。
- **冻结环境探测**（PyInstaller）：
  - `getattr(sys, "frozen", False)` 为真 → `base = Path(sys.executable).parent`。
  - 否则 → `base = Path(__file__).parent.parent`（仓库根）。
  - 候选 `base/web/dist` 存在则 `app.mount("/", StaticFiles(directory=..., html=True))`。
- 开发态启动：`uvicorn.run("server.main:app", host="127.0.0.1", port=8000, reload=True, reload_excludes=[".venv/*", "web/node_modules/*", "web/dist/*"])`。
- 冻结态启动（`packaging/app.py`）：直接传 `app` 对象，`reload=False`。

### 3.8 前端结构

- 构建：`web/vite.config.ts` — 端口 5173，`/api` 代理 `127.0.0.1:8000`；构建产物 `web/dist`。
- 类型：`web/src/api.ts` 镜像 `server/schemas.py`（AudioMeta / AudioListResponse / RecordStatusResponse / EffectInfo / EffectListResponse / ApplyEffectResponse / WaveformResponse / SpectrumResponse / AudioStatsResponse / HealthResponse）。
- 基础设施：`request<T>(path, opts?)` 处理 fetch 异常 → `"无法连接后端服务：…"`；非 2xx → 提取 `body.detail`；204 → `null`。
- 形态字段化：`schemaToFields(schema)` → `FormField[]`，按 `type / title / description / default / minimum / maximum` 投影；`EffectPanel.vue` 据此渲染 `<input type=range|number|checkbox>`，含 disabled `busy` 防双击。
- 状态中枢（`App.vue`）：
  - `audios / effects / selectedId / peaks / spectrum / stats / errorMessage / online`
  - `loadAnalysis(id)` 三个请求并行（`Promise.all`）
  - `clearAnalysis()` 在删除当前选中或停止播放前调用
  - `online` 由 `api.health()` 探测；首屏失败不抛错，只置 `false`
- 组件契约（`emit` 约定）：
  - `RecorderCard` → `recorded(meta)` / `error(msg)`
  - `AudioLibrary` → `select(id)` / `removed(id)` / `error(msg)`
  - `EffectPanel` → `applied(result)` / `error(msg)`
- 录音电平：前端 `setInterval(..., 300)` 轮询 `/api/audio/record/status`；`levelPercent = min(100, round(level*320))`（RMS 通常 0~0.3，×320 适合视觉指示）。
- 波形 / 频谱：`Canvas` + DPR 自适应；包络由 2000 个 min/max 点绘制；频谱 dB 裁剪 `[-90, 0]`。

---

## 4. 关键业务流程与数据流

### 4.1 录音 → 显示

```text
RecorderCard.start
  → api.startRecord({duration, sampleRate})
  → POST /api/audio/record/start   Recorder.start(sr, channels=1, duration)
  ← RecordStatusResponse{recording:true, elapsed:0, level:0}
RecorderCard 每 300ms
  → GET /api/audio/record/status
  ← RecordStatusResponse{recording, elapsed, level}
RecorderCard.finish / 自动到点
  → POST /api/audio/record/stop
  → Recorder.stop()  → _collect() = np.concatenate(chunks)
  ← AudioMeta{audio_id, sample_rate, channels, duration, created_at, label:"录音"}
App.handleRecorded
  → refreshAudios + selectAudio(meta.audio_id)
  → Promise.all(api.peaks / api.spectrum / api.stats)
  → 更新 peaks / spectrum / stats → WaveformCanvas / SpectrumCanvas 重绘
```

### 4.2 上传文件

```text
RecorderCard.upload
  → FormData.append("file")
  → POST /api/audio/upload
  → load_audio(bytes) → (data, sr) → store.put → AudioMeta
```

### 4.3 施加效果（默认产生新句柄）

```text
EffectPanel.apply
  → POST /api/effects/apply {audio_id, effect, params, save_as_new:true}
  → apply_effect(name, x, sr, params)
      ├─ get_effect(name)        # KeyError → 404
      ├─ model_validate(params)  # ValidationError → 422
      ├─ fn(x, sr, validated)     # 纯函数
      ├─ np.asarray(float32)
      ├─ 维度检查 1D/2D
      └─ np.clip(-1, 1)
  → store.put(result, sr, label="<原label> → <title>")  # save_as_new=true
  ← ApplyEffectResponse{audio_id, meta}
App.handleApplied
  → refreshAudios + selectAudio(new_id)   # 自动切到处理结果
```

### 4.4 删除 / 释放句柄

```text
AudioLibrary.remove
  → DELETE /api/audio/{id}
  → require_entry → store.delete
App.handleRemoved
  → 若被删的就是 selectedId：selectedId='' + clearAnalysis()
  → refreshAudios
```

### 4.5 打包分发

```text
scripts/build_release.ps1
  [1/6] web: npm run build → web/dist
  [2/6] uv sync ; uv run pyinstaller packaging/app.spec
        → release/pyinstaller/app/{app.exe + _internal/}
  [3/6] 组装 release/voice-system/
        ├─ copy pyinstaller/app/*    (exe + 运行时)
        ├─ copy web/dist → voice-system/web/dist/  (外置)
        ├─ 写入 start.bat (ASCII)
        └─ 写入 使用说明.txt (UTF-8 BOM)
  [4/6] Compress-Archive → release/voice-system.zip
  [5/6] 清理 release/pyinstaller 与 release/_build
  [6/6] 报告目录与 zip 大小
```

---

## 5. 对外接口与数据模型

### 5.1 HTTP 契约速查

完整 Pydantic 模型见 `server/schemas.py`；TS 类型镜像见 `web/src/api.ts`。本节只列**字段语义与约束**，便于代理推断改动影响。

| 模型 | 关键字段 | 约束 / 备注 |
|---|---|---|
| `EmptyParams` | — | 无参数效果的占位 |
| `AudioMeta` | `audio_id`, `sample_rate`, `channels`, `duration`, `created_at`, `label` | 波形本体不在此 |
| `AudioListResponse` | `items: AudioMeta[]` | |
| `RecordStartRequest` | `duration: float \| None ∈ [0.1,300]`（None = 手动停止），`sample_rate: int ∈ SUPPORTED_SAMPLE_RATES`，默认 48000 | |
| `RecordStatusResponse` | `recording: bool`, `elapsed: float`, `level: float`（RMS，0~1 典型） | |
| `EffectInfo` | `name`, `title`, `description`, `params_schema: dict`（JSON Schema） | 前端据此生成表单 |
| `EffectListResponse` | `items: EffectInfo[]` | |
| `ApplyEffectRequest` | `audio_id`, `effect`, `params: dict = {}`, `save_as_new: bool = True` | |
| `ApplyEffectResponse` | `audio_id`, `meta: AudioMeta` | |
| `SpectrumRequest` | `audio_id`, `n_fft ∈ [128,8192]`，默认 1024 | |
| `SpectrumResponse` | `audio_id`, `sample_rate`, `freqs: list[float]`, `magnitude_db: list[float]`，长度 n_fft/2+1 | |
| `WaveformResponse` | `audio_id`, `sample_rate`, `duration`, `points`, `minimum`, `maximum` | 固定 points 个点 |
| `AudioStatsResponse` | `audio_id`, `sample_rate`, `channels`, `duration`, `rms`, `peak` | rms ≤ peak |
| `ErrorResponse` | `detail: string` | FastAPI 全局 404 注册 |

### 5.2 错误码约定

| 状态码 | 触发场景 |
|---|---|
| 200 | 正常 |
| 204 | 播放 / 删除成功 |
| 400 | 上传空文件 / 录音参数非法（ValueError） |
| 404 | `audio_id` 不存在 / 未知效果器 |
| 409 | 录音已在进行 / 没有录音却 stop |
| 415 | 上传文件无法解码 |
| 422 | 录音空数据 / 效果器参数违反 Pydantic 约束 |
| 5xx | 框架 / 系统异常（当前未自定义） |

### 5.3 跨模块依赖图（简化）

```text
schemas.py        ← 类型基石，被所有上层 import
session_store.py  ← 只依赖 schemas / numpy / threading
core/registry.py  ← 只依赖 schemas / numpy / pydantic
core/analysis/*   ← 只依赖 numpy
core/io/*         ← 依赖 sounddevice / soundfile / schemas（DEFAULT_SAMPLE_RATE / SUPPORTED_SAMPLE_RATES）
core/effects/*    ← 依赖 registry + numpy；basic.py 另依赖 scipy.signal.resample_poly
api/deps.py       ← session_store
api/routers/*     ← schemas + session_store + core/{effects,analysis,io}
main.py           ← 装配 + 静态挂载；不写业务
web/src/api.ts    ← schemas 镜像（手动同步，无自动生成）
web/src/App.vue   ← api + 各组件
components/*      ← api（emit 与 props）
```

依赖方向严格向下，**`core/` 不应反向依赖 `api/`**。新增模块时请保持此方向。

---

## 6. 数据契约三条铁律（重申 · 不可破坏）

1. **内部音频 = `(np.ndarray[float32], sr:int)`**，值域 `[-1, 1]`。模块间禁止 WAV bytes / base64；Core 层不做重采样（变化只能在 `io/` 或显式声明的效果内）。
2. **audio_id 句柄制**：HTTP 只传 `audio_id`，波形不出后端。优点 = 接口负载恒定 + 处理历史天然成链（撤销直接可用）+ 唯一二进制接触面是 `/download`。
3. **效果器注册表**：新增算法只写 `server/core/effects/<name>.py` 一个文件 + 在 `__init__.py` 加 import。函数签名 `(np.ndarray, int, ParamsModel) -> np.ndarray`，**必须纯函数**（无全局状态、无 I/O、不改入参），输出由 `apply_effect` 规范化（float32 / 1D 或 2D / clip）。

违反任一条会导致难以察觉的隐性 bug；违反第三条会被同事的 PR 直接打回。

---

## 7. 拓展功能 · 当前状态与接入指南

> 阶段三目标（ADR 0006）：**三项必做**。状态均为 `[ ]`，需阶段二验收后开工。

### 7.1 语音克隆（`services/clone/`）

- 决策：本地 GPT-SoVITS，独立 Python venv + PyTorch + CUDA（见 ADR 0004）。
- **降级预案**：主干侧 `TTSProvider` 抽象接口预留云端实现插槽；当前**不实现**接口，只在 AD0004 留口。
- 接入位置：
  - 子服务目录仅有 `README.md`，目标接口 = `上传参考音频 → 提交文本 → 返回合成音频`。
  - 主干侧建议在 `services/` 增加 `client.py` 封装 HTTP 调用；接入 `server/api/routers/` 时**不要**改 `schemas.py`（新增请求/响应模型即可，旧接口不动）。
  - 合成音频**回流 SessionStore**：克隆结果以 `store.put` 形式产生新 `audio_id`，前端沿用 `AudioLibrary` 即可看到。
- 风险：CUDA / 模型权重 / 推理耗时，详见 ADR 0004 风险表。
- 注意：模型权重禁止入库；走 `scripts/download_models.py`（**尚未实现**，当前仅占位）。

### 7.2 录音质量检测（PLAN 3.2）

- 范围：录音完成后给出三项指标 + 综合建议（建议重录 / 质量合格）。
- 指标：
  - **音量过轻**：RMS / peak 与阈值比较。
  - **疑似爆音**：触顶样本（`np.isclose(|x|, 1.0, atol=...)`）占比。
  - **环境噪声**：利用无声段（短时能量低于阈值）估计底噪水平。
- 接入位置：
  - **首选纯函数 + 效果器注册表外的专用模块**（不是效果）：`server/core/analysis/quality.py`，暴露 `evaluate_quality(x, sr) -> QualityReport`。
  - 路由：新增 `server/api/routers/quality.py`：`POST /api/quality/{audio_id}/report` → `QualityReport`。
  - 契约：`server/schemas.py` 加 `QualityReport` 与子项模型（**全组同步**）。
  - 前端：`web/src/components/QualityCard.vue`（新增），通过 `api.qualityReport(id)` 调用；App 中在波形面板下挂载。
- 不复用效果器注册表的原因：检测不是「变换」，没有输入/输出波形对应，硬塞进注册表会污染语义。

### 7.3 语音加噪与降噪（PLAN 3.3）

- 范围：可调 SNR 的加噪 + 谱减法降噪；闭环验证（加噪 → 降噪 → 信噪比对比）。
- 接入位置（**严格走效果器铁律三**）：
  - `server/core/effects/noise_add.py`：`@register_effect(name="noise_add", title="加噪", ...)`；`NoiseAddParams{snr_db ∈ [-10, 40], noise_type ∈ ["white", ...]}`。
  - `server/core/effects/noise_reduce.py`：`@register_effect(name="noise_reduce", title="谱减法降噪", ...)`；参数含谱减系数、过减因子、噪声估计帧等。
  - 闭环验证脚本：`scripts/snr_loopback.py` 或 `tests/test_snr_loopback.py` —— 加噪 → 计算 SNR → 降噪 → 再算 SNR，断言「降噪后 SNR 显著高于加噪后」。
- SNR 计算可作为 `server/core/analysis/spectrum.py` 的扩展 `signal_to_noise_ratio(clean, noisy)`。

---

## 8. 质量与工程约束

### 8.1 Git 硬约束

- **每次改动后必须及时 git commit**（小步提交）。`AGENT.md` §8.1。
- 默认分支 `master`，直接提交；仅确需隔离时开 `feat/<模块>-<功能>`。
- 提交前：`uv run ruff check .` 与 `uv run pytest` 必须通过。
- 大文件禁止入库（模型权重、测试音频）；`uv.lock` 与 `package-lock.json` 必须入库。
- commit 信息：`feat|fix|refactor|docs|test(模块): 简述`。

### 8.2 工具链版本

- Python `>=3.11,<3.12`（`.python-version` 锁定，PyTorch 系轮子不全于 3.13/3.14）。
- uv 管理依赖；`pyproject.toml` 三组：`dev`(pytest/ruff/httpx/pyinstaller)、`prod`(pymupdf/python-docx，仅用于报告生成) + 默认。
- ruff：`line-length=100`、`target-version=py311`、select=`E,F,I,UP`、ignore=`E501`、exclude=`{.venv, services}`。
- pytest：`testpaths=["tests"]`、`pythonpath=["."]`（仓库根进 path，支持 `from server.xxx`）。
- 前端：`vue@^3.5.13`、`vite@^6`、`typescript@~5.6`、`vue-tsc@^2.1`，强制 TS（ADR 0005）。

### 8.3 提交前检查清单

```bash
uv run ruff check .
uv run pytest
# 前端改动：cd web && npm run build  (vue-tsc + vite)
```

### 8.4 测试现状

- `tests/test_api.py`：API 冒烟，覆盖健康 / 列表 / 上传 / 录音 / 效果施加（新建 / 覆盖 / 404 / 422）/ 波形包络 / 频谱形状 / 统计 / 下载 / 删除 / 错误句柄。
- `tests/test_effects.py`：Core 层纯函数：注册表非空、params_schema、reverse / gain / normalize / tempo 数值正确性、输出 dtype 与限幅、未知效果 / 非法参数、波形包络固定点数、频谱峰位（1000 Hz 单音 1kHz 附近 ±20Hz）。
- 历史快照：完整旧实现在 git `1c6e868`；清除后做架构文档与契约层重建。

---

## 9. 打包与运行

### 9.1 开发

```bash
uv sync                                # 后端依赖
uv run python -m server.main           # 后端 :8000
cd web && npm install && npm run dev   # 前端 :5173（代理 /api → 8000）
```

### 9.2 环境初始化

没有一键脚本（原 `scripts/setup.ps1` 已于 2026-09-07 删除），按 AGENT.md §3 逐步执行：

```bash
uv sync                 # 首次或依赖变更后：后端依赖
cd web && npm install   # 首次：前端依赖
uv run ruff check . && uv run pytest && uv run python scripts/smoke.py
```

### 9.3 一键打包

```bash
powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1
# 产物：release\voice-system\ (目录) + release\voice-system.zip (分发包)
# 启动：解压后双击 start.bat，自动打开 http://127.0.0.1:8000/
```

### 9.4 关键路径

| 路径 | 作用 |
|---|---|
| `web/dist/` | 前端构建产物；开发态由 Vite 代理，冻结态由 FastAPI 托管 |
| `release/voice-system/` | 解压即用目录 |
| `release/_build/` 与 `release/pyinstaller/` | PyInstaller 中间产物（打包脚本结束后会清理） |
| `.venv/` | uv 创建的虚拟环境 |
| `docs/sessions/YYYY-MM-DD-<主题>.md` | 每次 session 收工日志（必写） |

---

## 10. 风险与对策（摘录 AGENT.md §10）

| 风险 | 对策 |
|---|---|
| GPT-SoVITS 环境配置失败 | 独立 venv + 进程隔离；`TTSProvider` 抽象层保留云端插槽 |
| Python 版本漂移 | `.python-version` 锁 3.11，uv 强制 |
| 模型权重数 GB 入库 | `.gitignore` + `scripts/download_models.py`（待实现） |
| 实时性不达标 | 文件级处理优先；后续若要流式需重新评估 |
| 多人改同一文件冲突 | 小步提交 + 频繁 rebase；`schemas.py` 改动全组同步 |

---

## 11. AGENT 快速接手 Checklist（执行模板）

1. 读 `AGENT.md` → 读 `PLAN.md` 定位阶段与下一个待办。
2. 读本文档第 0~5 节 → 建立模块心智模型。
3. 读 `docs/sessions/` 最新一份收工日志 → 了解上一次做了什么、坑是什么。
4. `uv sync`（必要时）→ `uv run ruff check .` + `uv run pytest` 确认起点干净。
5. 启动后端 `uv run python -m server.main` 与前端 `cd web && npm run dev`，打开 `http://127.0.0.1:5173` 与 `/docs` 验证链路。
6. 动手前确认改动落在哪一层：
   - 改契约 → 同步 `schemas.py` + `web/src/api.ts` + ADR（如适用）。
   - 加效果 → 新建 `server/core/effects/<name>.py` + `__init__.py` 加 import。
   - 加分析 → 新建 `server/core/analysis/<name>.py`；路由层新建文件并在 `main.py` include。
   - 加前端组件 → `web/src/components/`，仅通过 `emit` 与 `App.vue` 通信。
7. 收工：更新 `PLAN.md`、写 `docs/sessions/<date>-<topic>.md`、必要时在 AGENT.md §11 / §12 追加。

---

## 12. 索引 · 关键文件速查

```text
契约        server/schemas.py                web/src/api.ts
句柄仓库    server/session_store.py
注册表      server/core/registry.py
效果        server/core/effects/__init__.py
            server/core/effects/basic.py
分析        server/core/analysis/spectrum.py
I/O         server/core/io/device.py         (Recorder / Player)
            server/core/io/audio_file.py     (load_audio / dump_audio)
路由        server/api/routers/audio.py
            server/api/routers/effects.py
            server/api/routers/analysis.py
公共依赖    server/api/deps.py
入口        server/main.py                   (含冻结探测)
打包入口    packaging/app.py                 packaging/app.spec
打包脚本    scripts/build_release.ps1
冒烟脚本    scripts/smoke.py
前端入口    web/src/main.ts                  web/src/App.vue
测试        tests/test_api.py                tests/test_effects.py
配置        pyproject.toml                   web/vite.config.ts            web/package.json
真相源      AGENT.md                         PLAN.md
决策        docs/adr/0001..0006              docs/sessions/
```

---

_本文件由 AGENT 阅读生成，配合 AGENT.md / PLAN.md / ADR 系列使用。如有结构性变更（新增模块、依赖方向反转、新增打包形态），请同步更新本文并在 AGENT.md §12 变更日志记一行。_
