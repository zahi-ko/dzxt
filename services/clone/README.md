# services/clone/ · 语音克隆子服务（3.1）

必做拓展功能：本地 GPT-SoVITS 语音克隆（zero-shot）。

## 架构

```
主干 FastAPI(8000) ──HTTP──▶ 本适配层(9900) ──HTTP──▶ GPT-SoVITS 引擎(9880)
     TTSProvider              轻量 FastAPI              官方整合包
     (server/tts_provider.py) 参考音频托管              api_v2.py
```

- **引擎**：官方整合包（含 runtime/PyTorch/CUDA 与预训练权重），独立进程，
  目录 `C:\Users\zahi\.venvs\GPT-SoVITS-v2pro-20250604`。本仓库不提交任何权重。
- **适配层**：本目录。**不含 torch**，只做参考音频托管与合成转发。
  独立 venv，与主干 uv 环境互不污染。
- **降级预案**（ADR 0004）：云端 TTS 只需新增 `TTSProvider` 子类，路由与前端零改动。

## 启动（两个终端，合成前引擎必须先起）

**1. 引擎**（GPT-SoVITS api_v2，CUDA + fp16，**v2ProPlus** 预训练模型）：

```powershell
cd C:\Users\zahi\.venvs\GPT-SoVITS-v2pro-20250604
.\runtime\python.exe api_v2.py -a 127.0.0.1 -p 9880
```

**2. 适配层**：

```powershell
cd C:\Users\zahi\Desktop\dzxt\services\clone
.venv\Scripts\python.exe main.py
```

首次部署：`uv venv --python 3.11 .venv` 后按 `pyproject.toml` 安装依赖。

环境变量：`CLONE_ENGINE_URL`（默认 `http://127.0.0.1:9880`）、
`CLONE_ADAPTER_PORT`（默认 9900）；主干侧 `CLONE_SERVICE_URL`（默认 9900）。

引擎模型版本：`GPT_SoVITS/configs/tts_infer.yaml` 的 custom 段。当前 **v2ProPlus**
（2026-09-08 切换，原份 v2 配置备份在同目录 `tts_infer.v2.bak.yaml`）；改完需重启引擎生效。

## 接口（主干 `/api/clone/*` 一一代理，前端只与主干通信）

| 适配层端点 | 方法 | 说明 |
|---|---|---|
| `/health` | GET | 自身 + 引擎探活 |
| `/refs` | POST | 上传参考音频（multipart，常见音频格式均收，2–15s） |
| `/refs` | GET | 列出参考音频 |
| `/refs/{id}` | PATCH | 修改参考文本 |
| `/refs/{id}` | DELETE | 删除参考音频 |
| `/refs/{id}/export` | GET | 导出音色 .clone（voice.json + ref.wav） |
| `/refs/import` | POST | 导入 .clone 音色文件 |
| `/synthesize` | POST | 合成，返回 WAV 字节（同步，单句秒级） |

引擎不可达时统一 503，主干翻译为「克隆子服务未就绪」提示。

## 合成参数（/synthesize 请求体，默认值与引擎 api_v2 一致）

| 参数 | 默认 | 效用 |
|---|---|---|
| `text_lang` / `prompt_lang` | `zh` | 合成文本 / 参考文本的语言（zh/en/ja/ko/yue/auto），决定发音分支 |
| `speed_factor` | 1.0 | 语速倍率（0.5–2.0） |
| `text_split_method` | `cut5` | 长文本切句策略 cut0–cut5（影响停顿节奏与长句稳定性） |
| `batch_size` | 1 | 并行合成句数，越大越快、越吃显存（**仅填写参考文本时生效**；无参考文本的 prompt-free 模式引擎不支持批量，适配层自动归一为 1） |
| `fragment_interval` | 0.3 | 切句拼接处的静音秒数 |
| `temperature` | 1.0 | 采样温度（越高越随机起伏，越低越平直） |
| `top_k` / `top_p` | 15 / 1.0 | 采样范围截断（越小越保守） |
| `repetition_penalty` | 1.35 | 重复惩罚（抑制复读卡顿） |
| `seed` | -1 | 随机种子（-1 随机；固定后同文本同参数可复现） |

前端 ClonePanel「高级参数」区已内置以上全部项并带效用说明。
记忆策略分两级：**高级参数仅本次运行内记忆**（sessionStorage，重开程序恢复默认）；
**参考音选择、合成文本持久记忆**（localStorage，重开沿用上一次）；
参考文本由参考音记录（后端）承载，选中即恢复。

## 参考音频要求

- **格式**：wav / mp3 / flac / ogg / opus / m4a / aac / wma / webm / aiff 均可上传。
  解码统一走 `common/audio_codec.py`（与主干同一份实现）：
  soundfile 主路径，解不动的走 ffmpeg 兜底（管道直解优先，失败退临时文件重试）；
  最终统一转写为 PCM_16 WAV 落盘，引擎侧只面对 wav。
  ffmpeg 查找顺序：环境变量 `CLONE_FFMPEG` → 引擎整合包 → 系统 PATH。
- **展示名归一**：上传后文件名统一改为 .wav（如 `song.mp3` → `song.wav`），
  表示已完成自动转换。
- **时长**：5–10 秒清晰人声（受理 2–15s）
- **必须填写参考文本**（这段音频说了什么）——参与音色与韵律对齐，
  空文本会明显劣化克隆质量
- 文件落盘 `wavs/`，索引 `wavs/refs.json`；均不入库（根 .gitignore）

## 音色保存与导入（.clone 文件）

- **导出**：`GET /refs/{id}/export`（主干 `/api/clone/refs/{id}/export` 代理），
  前端「导出音色」按钮下载 `<音色名>.clone`。
- **格式**：ZIP 容器（后缀 .clone），内含 `voice.json`（音色名、参考文本、
  预设合成文本、时长/采样率）+ `ref.wav`。**不含任何模型权重**——zero-shot
  克隆只需参考音频，导入方无需安装引擎即可还原配置。
- **导入**：`POST /refs/import`（主干 `/api/clone/refs/import` 代理），
  还原为一条参考音频 + 参考文本；若包内带预设合成文本，前端选中后自动填入
  合成文本框。
- 预设合成文本 = 该音色最近一次成功合成的文本（合成时自动记录）。

## 冒烟验证（手动）

```powershell
# 引擎探活
curl http://127.0.0.1:9880/openapi.json -o $null -w "%{http_code}"
# 适配层探活（应返回 engine_online: true）
curl http://127.0.0.1:9900/health
# 端到端合成
curl "http://127.0.0.1:9900/synthesize" -H "Content-Type: application/json" `
  -d '{"ref_id":"<id>","text":"语音克隆环境验证","prompt_text":"参考文本"}' --output out.wav
```

架构决策见 `docs/adr/0004-voice-clone-local.md`（含 2026-09-08 实施修订）。
