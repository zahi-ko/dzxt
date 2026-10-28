# 运行说明

本仓库为前后端分离 + 两个可选子服务的结构。**只有主干(8000)是必需的**，两个子服务
（语音克隆、加噪降噪）缺失时对应功能降级，其余功能不受影响。

仓库内没有可通用的启动脚本（`start.bat` 是作者本机便捷脚本，路径写死且被 git 忽略），
请按本文手动启动。

## 1. 环境要求

| 依赖 | 版本 | 用途 |
|---|---|---|
| Python | **3.11**（`.python-version` 锁定） | 主干与两个子服务；3.13/3.14 上 PyTorch 系轮子不全 |
| [uv](https://docs.astral.sh/uv/) | 最新 | 创建 venv、安装依赖、运行命令 |
| Node.js | 18+ | 前端（Vite） |
| ffmpeg | 可选 | 参考音频/上传音频的兜底解码（m4a、VBR mp3 等） |
| GPU | 可选 | 语音克隆需要 NVIDIA 显存 ≥ 6GB（GPT-SoVITS 推理） |

## 2. 服务与端口

| 服务 | 目录 | 端口 | 必需 |
|---|---|---|---|
| 主干（FastAPI） | `server/` | 8000 | ✅ |
| 前端开发服务器（Vite） | `web/` | 5173 | 开发态 |
| 语音克隆适配层 | `services/clone/` | 9900 | 可选（克隆功能） |
| 语音克隆引擎（GPT-SoVITS `api_v2.py`） | 仓库外整合包 | 9880 | 可选（克隆功能） |
| 语音加噪与降噪 | `services/noise/` | 9910 | 可选（加噪降噪功能） |

启动顺序：**子服务先于主干**（主干启动时会探活，晚起也不影响，界面点「刷新状态」即可）。

## 3. 首次部署

```powershell
# 主干依赖（在仓库根目录）
uv sync

# 前端依赖
cd web
npm install
cd ..

# 加噪降噪子服务（独立 venv）
cd services\noise
uv venv --python 3.11 .venv
uv sync
cd ..\..

# 语音克隆适配层（独立 venv，无 torch）
cd services\clone
uv venv --python 3.11 .venv
uv sync
cd ..\..
```

GPT-SoVITS 引擎不属于本仓库：下载官方整合包（含 `runtime/` 与预训练权重）解压到任意目录，
克隆功能默认读取该目录下的 `GPT_SoVITS/configs/tts_infer.yaml` 选择模型。

## 4. 启动

开多个终端，各自常驻。

**① 主干（必起）**

```powershell
uv run python -m server.main          # http://127.0.0.1:8000
```

接口文档：<http://127.0.0.1:8000/docs>

**② 前端（开发态）**

```powershell
cd web
npm run dev                           # http://127.0.0.1:5173
```

Vite 已把 `/api/*` 代理到 `127.0.0.1:8000`；后端换端口时用 `BACKEND_URL` 覆盖。

**③ 加噪降噪子服务（可选）**

```powershell
cd services\noise
.venv\Scripts\python.exe main.py      # 127.0.0.1:9910
```

macOS / Linux 把 `.venv\Scripts\python.exe` 换成 `.venv/bin/python`。

**④ 语音克隆（可选，两个进程都要起）**

```powershell
# 引擎：路径换成你自己的整合包目录
cd <GPT-SoVITS 整合包目录>
.\runtime\python.exe api_v2.py -a 127.0.0.1 -p 9880

# 适配层
cd <仓库>/services/clone
.venv\Scripts\python.exe main.py      # 127.0.0.1:9900
```

## 5. 生产模式（单端口）

构建前端后由主干直接托管静态资源，只需起 8000 一个端口：

```powershell
cd web
npm run build                         # 产出 web/dist
cd ..
uv run python -m server.main          # 访问 http://127.0.0.1:8000
```

打包分发（PyInstaller + zip）见 `scripts/build_release.ps1`。

## 6. 环境变量

| 变量 | 读取方 | 默认 | 说明 |
|---|---|---|---|
| `BACKEND_URL` | 前端（Vite） | `http://127.0.0.1:8000` | 开发代理目标 |
| `CLONE_SERVICE_URL` | 主干 | `http://127.0.0.1:9900` | 克隆适配层地址 |
| `CLONE_ENGINE_URL` | 克隆适配层 | `http://127.0.0.1:9880` | GPT-SoVITS 引擎地址 |
| `CLONE_ADAPTER_HOST` / `CLONE_ADAPTER_PORT` | 克隆适配层 | `127.0.0.1` / `9900` | 监听地址 |
| `CLONE_FFMPEG` | 克隆适配层 | 自动查找 | ffmpeg 可执行文件路径 |
| `NOISE_SERVICE_URL` | 主干 | `http://127.0.0.1:9910` | 加噪降噪服务地址 |
| `NOISE_ADAPTER_HOST` / `NOISE_ADAPTER_PORT` | 加噪降噪服务 | `127.0.0.1` / `9910` | 监听地址 |
| `NOISE_MAX_UPLOAD_MB` | 加噪降噪服务 | `100` | 上传体积上限 |

主干监听地址与端口写死在 `server/main.py`（`127.0.0.1:8000`），改端口需同时改前端代理。

## 7. 启动后验证

```powershell
curl http://127.0.0.1:8000/health                       # {"status":"ok","effects":...}
curl http://127.0.0.1:9900/health                       # engine_online: true 表示引擎可达
curl http://127.0.0.1:9910/health                       # {"status":"ok","operations":2}
```

浏览器打开 <http://127.0.0.1:5173>：顶栏状态胶囊显示「后端已连接」，底部拓展卡片
显示「在线」即两个子服务就绪。

## 8. 测试与检查

```powershell
uv run ruff check .
uv run pytest
uv run python scripts/smoke.py        # 端到端冒烟：采集→显示→处理→历史→播放/导出

cd services\noise
uv run pytest                         # 子服务单测
```

## 9. 关于 start.bat

`start.bat` 是作者本机的便捷启动脚本，内含写死的绝对路径（整合包位置、仓库位置），
**换机器不可直接用**；它也写在 `.gitignore` 里，不随仓库分发。

需要自己的版本时，按第 4 节复制四条启动命令即可，把路径替换为本机路径，例如：

```bat
@echo off
cd /d <仓库>\services\noise
start "noise-9910" ".venv\Scripts\python.exe" main.py

cd /d <仓库>
start "backend-8000" ".venv\Scripts\python.exe" -m server.main

cd /d <仓库>\web
start "web-5173" cmd /c "npm run dev"
```

注意 `npm run dev` 会前台阻塞，必须用 `start cmd /c` 包一层，否则其后的命令不会执行。
