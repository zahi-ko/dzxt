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
| `/synthesize` | POST | 合成，返回 WAV 字节（同步，单句秒级） |

引擎不可达时统一 503，主干翻译为「克隆子服务未就绪」提示。

## 参考音频要求

- **格式**：wav / mp3 / flac / ogg / opus / m4a / aac / wma / webm / aiff 均可上传。
  soundfile 主路径解码，解不动的（m4a/aac/wma/webm 等）走 ffmpeg 兜底
  （管道直解优先，mp4 系 moov-at-end / 0 帧空输出等失败自动退临时文件重试）；
  最终统一转写为 PCM_16 WAV 落盘，引擎侧只面对 wav。
  ffmpeg 查找顺序：环境变量 `CLONE_FFMPEG` → 引擎整合包 → 系统 PATH。
- **时长**：5–10 秒清晰人声（受理 2–15s）
- **必须填写参考文本**（这段音频说了什么）——参与音色与韵律对齐，
  空文本会明显劣化克隆质量
- 文件落盘 `wavs/`，索引 `wavs/refs.json`；均不入库（根 .gitignore）

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
