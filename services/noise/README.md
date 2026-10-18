# noise-service · 语音加噪与降噪子服务（dzxt 3.3）

必做拓展功能：**语音加噪与降噪**——可调信噪比的加噪 + 谱减法（Spectral Subtraction）
降噪，形成「加噪 → 降噪 → SNR 对比」闭环验证。

## 架构

```
主干 FastAPI(8000) ──HTTP──▶ 本服务(9910)     无状态、不落盘、不含模型
     NoiseProvider            谱减/加噪纯函数
     (server/noise_provider.py)
```

- **本服务**：`services/noise/`（dzxt 仓库内，与 `services/clone` 同组织模式），
  独立 venv（Python 3.11，`uv sync` 创建），源码随 dzxt git 管理。
  与 dzxt 主干的唯一耦合是 HTTP 接口 + 主干的环境变量 `NOISE_SERVICE_URL`。
- **降级预案**：本服务离线时主干仅失去加噪/降噪能力（`/api/noise/status`
  返回 `online=false`），基础功能不受影响；切换实现只需替换
  `NoiseProvider` 子类，路由与前端零改动。
- **DSP 核心**：`app/dsp.py`，来自用户提供的 `n1.py`，算法与默认值原样保留，
  纯函数、单声道；立体声在 `app/audio.py` 逐通道分发（谱减的噪声估计与加噪的
  噪声叠加都不能像 gain 那样广播，dzxt 曾在此栽过 500）。

## 启动

```powershell
cd services\noise            # 相对 dzxt 仓库根目录
.venv\Scripts\python.exe main.py        # 默认监听 127.0.0.1:9910
```

首次部署：

```powershell
uv venv --python 3.11 .venv
uv sync                                # 按 pyproject.toml 安装依赖
uv run pytest                          # 29 项测试
uv run ruff check .
```

环境变量：`NOISE_ADAPTER_HOST` / `NOISE_ADAPTER_PORT`（默认 `127.0.0.1` / `9910`）、
`NOISE_MAX_UPLOAD_MB`（默认 100）；主干侧 `NOISE_SERVICE_URL`（默认 9910）。

## 接口（主干 `/api/noise/*` 一一代理，前端只与主干通信）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/health` | GET | 健康检查 |
| `/operations` | GET | 列出操作与参数 JSON Schema（前端动态表单依据） |
| `/add-noise` | POST | 加噪，multipart（file + snr_db/noise_type/seed），返回 WAV 字节 |
| `/denoise` | POST | 谱减降噪，multipart（file + alpha/beta/frame_ms/hop_ms/noise_est_ratio/noise_frames/gain_smooth），返回 WAV 字节 |
| `/snr` | POST | 计算实际信噪比，multipart（clean + noisy 两个文件），返回 `{"snr_db": ...}` |

- 入参校验失败 → 422（Pydantic 错误明细）；音频解不动 → 415；超限 → 413。
- 输入输出采样率一致，本服务不做重采样（重采样只发生在主干 io 层）。
- 输入仅支持 libsndfile 可读格式（WAV/FLAC/OGG 等）；主干侧上传已统一转 WAV，
  正常链路只会收到 WAV。

## 加噪参数（/add-noise）

| 参数 | 默认 | 效用 |
|---|---|---|
| `snr_db` | 10.0 | 目标信噪比（-5–60 dB），越大越干净 |
| `noise_type` | `white` | 噪声类型：white 白噪声 / pink 粉噪声（1/f）/ brown 布朗噪声（1/f²） |
| `seed` | 随机 | 随机种子，固定后同输入同参数可复现（立体声按声道偏移，声道间不相关） |

## 降噪参数（/denoise，默认值与 n1.py 一致）

| 参数 | 默认 | 效用 |
|---|---|---|
| `frame_ms` / `hop_ms` | 25 / 10 | 帧长 / 帧移（毫秒） |
| `alpha` | 2.0 | 过减因子，越大降噪越狠、失真与音乐噪声越明显（常用 1.5–3.0） |
| `beta` | 0.02 | 谱底系数，噪声残留下限，防谱减过度产生空洞 |
| `noise_est_ratio` | 0.15 | 自适应噪声估计：取能量最低帧的比例 |
| `noise_frames` | 自适应 | 指定用前 N 帧估计噪声谱（有纯噪声段时更准） |
| `gain_smooth` | 0.5 | 增益时间平滑系数（0–0.99），抑制音乐噪声 |

## 冒烟验证（手动）

```powershell
# 探活
curl http://127.0.0.1:9910/health
# 加噪（SNR 10dB 白噪声）
curl -F "file=@clean.wav" -F "snr_db=10" -F "noise_type=white" -F "seed=42" `
  http://127.0.0.1:9910/add-noise --output noisy.wav
# 降噪
curl -F "file=@noisy.wav" -F "alpha=2.0" http://127.0.0.1:9910/denoise --output denoised.wav
# SNR 对比（闭环验证）
curl -F "clean=@clean.wav" -F "noisy=@noisy.wav" http://127.0.0.1:9910/snr
```

架构决策见 dzxt 仓库 `docs/adr/0008-noise-standalone-service.md`。
