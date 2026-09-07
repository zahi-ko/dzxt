# AGENT.md

语音处理系统设计与实现 · 项目总纲。

**本文件是项目的唯一真相源。** 任何新 session 开工前必须先读完本文件，再动手。
内容有变化时，改动者负责同步更新，并在文末「变更日志」记一行。

---

## 0. 新 session 开工清单

按顺序做完这五步，再开始写代码：

1. 读本文件全文
2. 读 `PLAN.md`，定位当前处于哪个阶段、下一个待办是什么
3. 确认环境可用：`uv sync`（首次或依赖变更后），再 `uv run ruff check .`
4. 打开 `http://127.0.0.1:5173`（前端）与 `http://127.0.0.1:8000/docs`（接口文档）
5. 收工前回来更新「当前进展」与「变更日志」

---

## 1. 项目概况

| 项 | 内容 |
|---|---|
| 题目 | 语音处理系统设计与实现（第 14 组，团队题） |
| 指导教师 | 张彪 |
| 成员 | 张翔（组长）、王仁智、叶绍文 |
| 成果形式 | 软件 |
| 阶段 | 开题 → 中期 → 结题 |

**任务要求（来自题目表）**

1. 完成语音处理系统软件整体架构设计与实现，系统运行稳定、界面友好
2. 实现语音信号的采集、处理、显示、播放
3. 拓展功能（语音识别、语音合成、语音克隆与检测、语音助手等）**至少实现一项**且结果正确可靠

**本项目已确定的拓展范围（共三项，均必做）**

- 语音克隆（本地 GPT-SoVITS）
- 录音质量检测：评估音量过轻、疑似爆音、环境噪声嘈杂程度，综合判断并给出是否需要重录的建议
- 语音加噪与降噪：可调信噪比的加噪 + 降噪处理，形成加噪 → 降噪闭环验证
- 明确不做：语音识别、语音合成、端点检测、语音助手、深度伪造检测

> 范围一旦要变，先在 `docs/adr/` 补一篇决策记录，再动代码。

---

## 2. 技术栈（已锁定，不要随意更换）

| 层 | 选型 | 说明 |
|---|---|---|
| 运行时 | **Python 3.11**（`.python-version` 锁定） | 3.13/3.14 上 PyTorch 系轮子不全 |
| 环境管理 | **uv** + `pyproject.toml` + `uv.lock` | 跨 session 秒级复现 |
| Web 框架 | **FastAPI** + Pydantic v2 + uvicorn | 自动 OpenAPI 即接口契约 |
| 音频 I/O | **sounddevice** + **soundfile** | 采集播放与文件读写 |
| DSP | **numpy** + **scipy.signal** | 不引入 librosa，算法自行实现便于答辩讲原理 |
| 前端 | **Vue 3 + TypeScript + Vite** | 组件化 + 响应式；TS 类型约束提升鲁棒性（见 `docs/adr/0005-frontend-typescript.md`） |
| 测试 | pytest | Core 层纯函数优先覆盖 |
| 代码检查 | ruff | 提交前必跑 |

**语音克隆子服务**（`services/clone/`）：Python 3.11 + PyTorch + GPT-SoVITS，**独立虚拟环境**，通过 HTTP 与主干通信。详见 `docs/adr/0004-voice-clone-local.md`。

---

## 3. 环境与启动

### 3.1 后端

```bash
uv sync              # 首次或依赖变更后执行
uv run python -m server.main    # 启动后端，默认 http://127.0.0.1:8000
```

接口文档自动生成：`http://127.0.0.1:8000/docs`

### 3.2 前端

```bash
cd web
npm install          # 首次
npm run dev          # 开发服务器 http://127.0.0.1:5173
npm run build        # 产出 web/dist，由后端托管
```

Vite 已配置代理：前端所有 `/api/*` 请求自动转发到 `127.0.0.1:8000`，因此前端代码里**一律写相对路径 `/api/...`**，不要硬编码端口。

### 3.3 硬件环境

本机为 **NVIDIA RTX 4060 Laptop / 8GB 显存**，满足 GPT-SoVITS 推理需求。
换机器开发时，先跑 `nvidia-smi` 确认显存是否 ≥ 6GB。

---

## 4. 数据契约（三条铁律）

这三条是所有模块协作的基础，违反会导致隐秘 bug，**任何情况下不得破坏**。

### 铁律一：内部音频表示唯一

模块间传递的音频**一律**是 `(np.ndarray[float32], sample_rate: int)`，值域 `[-1, 1]`。

- 禁止在模块间传递 WAV bytes、base64 字符串
- 禁止在 Core 层内部做重采样；采样率变化只能发生在 `io/` 层或显式声明的效果里
- 单声道用一维数组 `(n,)`，多声道用二维 `(n, channels)`

### 铁律二：audio_id 句柄制

音频实体存放在后端 `SessionStore`，API 请求与响应**只传 `audio_id`**，不传波形。

- 好处一：音频再长，接口负载不变
- 好处二：处理历史天然形成链表，撤销/对比功能直接可用
- 前端唯一接触音频二进制的场景是**导出下载与播放流**（`GET /api/audio/{id}/stream`），
  二者都是终点消费；链路内部依旧只传 `audio_id`。播放放前端的原因见 ADR 0007

### 铁律三：效果器注册表

新增处理算法**只写一个文件、一个纯函数**，不允许改动路由、Service 或前端。

```python
# server/core/effects/my_effect.py
from pydantic import BaseModel, Field
import numpy as np
from server.core.registry import register_effect

class MyParams(BaseModel):
    amount: float = Field(default=1.0, ge=0.0, le=4.0, description="处理强度")

@register_effect(name="my_effect", title="我的效果", description="一句话说明")
def my_effect(x: np.ndarray, sr: int, params: MyParams) -> np.ndarray:
    return x * params.amount
```

文件放到 `server/core/effects/` 并在该目录 `__init__.py` 中 import 即完成接入。
参数模型的 JSON Schema 由 `GET /api/effects` 自动下发，前端据此生成表单。

**效果函数必须是纯函数**：相同输入必得相同输出，不碰全局状态、不做 I/O、不改入参。

---

## 5. 目录结构

```
dzxt/
├── AGENT.md              本文件
├── PLAN.md               三阶段里程碑
├── pyproject.toml        依赖声明
├── uv.lock               锁定版本，务必入库
│
├── server/
│   ├── main.py           FastAPI 入口
│   ├── schemas.py        【契约层】Pydantic 模型，唯一接口真相源
│   ├── session_store.py  audio_id 句柄仓库
│   ├── api/
│   │   ├── deps.py       路由公共依赖（句柄 → 404）
│   │   └── routers/      audio / effects / analysis / realtime(ws)
│   └── core/
│       ├── registry.py   效果器注册表
│       ├── effects/      处理算法，一个效果一个文件
│       ├── analysis/     频谱、语谱图、波形包络
│       └── io/           录音播放、文件读写
│
├── web/
│   ├── index.html
│   ├── vite.config.ts    /api 代理到 8000
│   └── src/
│       ├── main.ts
│       ├── App.vue       状态中枢（<script setup lang="ts">）
│       ├── api.ts        【唯一后端耦合点】接口类型定义镜像 server/schemas.py
│       └── components/   采集 / 列表 / 播放器 / 波形 / 频谱 / 语谱图 / 效果与历史
│
├── services/
│   └── clone/            语音克隆子服务，独立环境（待实现）
│
├── docs/
│   ├── adr/              架构决策记录
│   └── sessions/         每个 session 的收工日志
│
├── tests/                pytest
└── scripts/              打包与冒烟脚本（smoke.py 为提交前必跑）
```

---

## 6. 模块归属

**这是默认归属与评审归属，不是排他锁。** 任何人都可以改任何文件，但改了别人主要负责的模块，需在「变更日志」记一行并知会对方。

| 模块 | 主要负责人 | 备注 |
|---|---|---|
| `server/schemas.py` | 待分配 | **改动必须全组同步**，这是唯一硬约束 |
| `server/core/effects/` | 待分配 | 纯算法，最易并行 |
| `server/core/analysis/` | 待分配 | 频谱、语谱图 |
| `server/core/io/` | 待分配 | 设备与文件 |
| `server/api/` | 待分配 | 路由层 |
| `web/` | 待分配 | Vue 前端 |
| `services/clone/` | 待分配 | 独立环境，门槛最高 |
| `docs/` | 组长 | 文档与决策记录 |

> 分工确定后直接改这张表。

---

## 7. API 设计约定

- **REST 负责命令**，路径前缀 `/api`，资源名复数或语义化：`/api/audio`、`/api/effects`、`/api/analysis`
- **WebSocket 负责实时推送**（录音电平、频谱流），路径 `/ws/...`
- 所有请求/响应体必须有 Pydantic 模型，**禁止裸 dict**
- 错误统一返回 `{"detail": "..."}` + 合适状态码
- 接口优先：先写 schema 与返回 mock 的 router stub，前端即可并行开工，不等后端实现

**前端对称约束**：所有网络请求封在 `web/src/api.ts`，并在此定义与 `server/schemas.py` 对应的 TS 类型；Vue 组件不直接调用 `fetch` 或 `axios`。源码一律 TypeScript，禁止混入裸 `.js` 源文件。

---

## 8. 协作规范

### 8.1 Git

- **每次改动后都必须及时使用 git 提交**——这是硬性约束。小步提交，做完一件事立刻 commit，不攒批量、不过夜；提交前跑检查命令（见下）
- 默认分支为 **`master`**，**直接在 `master` 上提交，不另开开发分支**。仅在确需隔离（如大重构、并行实验）时临时开分支，但非强制
- 开发分支命名：`feat/<模块>-<功能>`，例：`feat/effects-tempo`、`feat/web-waveform`（仅在确需隔离时使用）
- 提交信息：`feat|fix|refactor|docs|test(模块): 简述`
- 提交前必须：

```bash
uv run ruff check .
uv run pytest
uv run python scripts/smoke.py   # 端到端冒烟：采集→显示→处理→历史→播放/导出
```

- 大文件（模型权重、测试音频）**禁止入库**，一律 `.gitignore` + `scripts/` 下载脚本
- `uv.lock`、`package-lock.json` 必须入库

### 8.2 评审

- `server/schemas.py` 改动 → 全组同步
- 其余改动 → 知会对应模块负责人即可

---

## 9. 跨 session 工作流

**开工**：读 `AGENT.md` → 读 `PLAN.md` → 确认环境 → 动手

**收工**：

1. 更新 `PLAN.md` 中已完成的条目（勾选）
2. 更新本文件「当前进展」
3. 在「变更日志」追加一行
4. 在 `docs/sessions/YYYY-MM-DD-<主题>.md` 写一份日志，包含：
   - 本次做了什么
   - 遗留问题与坑
   - 下一个 session 从哪里接手

第 4 步最关键——它决定了下一个 session 是 5 分钟进入状态，还是半小时考古。

> **规则（2026-09-07）**：报告与 PPT 类交付物，未显式要求时直接跳过，不列入待办。

---

## 10. 风险登记

| 风险 | 影响 | 对策 |
|---|---|---|
| GPT-SoVITS 环境配置失败 | 结题无法交付拓展功能 | 独立进程 + 独立环境隔离；`TTSProvider` 抽象层保留云端实现插槽（当前不实现，接口留好） |
| Python 版本漂移 | 依赖装不上 | `.python-version` 锁 3.11，uv 强制 |
| 模型权重数 GB 污染仓库 | 仓库膨胀、clone 失败 | `.gitignore` + 下载脚本 |
| 实时性不达标 | 演示卡顿 | 采用文件级处理而非严格流式 |
| 多人改同一文件冲突 | 合并地狱 | 小步提交 + 频繁 rebase |

---

## 11. 当前进展

**阶段：中期（2.1 采集 / 2.2 显示 / 2.3 处理 / 2.4 播放 / 2.5 工程质量 全部完成）**

> 2026-09-02：应用户要求清除了全部具体代码（实现前已提交完整备份快照 `1c6e868`，需要参考旧实现可 `git show 1c6e868:<path>` 查看）。技术栈、数据契约、目录职责等架构约定全部保留，各模块目录已补 README 说明目标结构与职责。

已完成：

- [x] 技术栈选型与架构设计（见 `docs/adr/`）
- [x] 仓库初始化、目录骨架（含各模块 README 与 .gitkeep）
- [x] Python 3.11 环境 + 主干依赖锁定（`pyproject.toml` + `uv.lock`）
- [x] 项目文档：AGENT.md、PLAN.md、ADR 0001–0004
- [x] 拓展功能范围确定（2026-09-06）：语音克隆 + 录音质量检测 + 语音加噪与降噪，共三项必做（ADR 0006）
- [x] 契约层 `server/schemas.py` 与 `session_store.py`（2026-09-02）
- [x] 1.3 接口骨架全部条目（2026-09-02）：注册表与基础效果、音频 I/O、main.py 与三个路由、Vue 3 + TS 前端、前后端联调（真实麦克风录音 → 波形 → 播放 → 效果 → 下载全链路验证通过）
- [x] `scripts/setup.ps1` 一键环境脚本（2026-09-02 落位，**2026-09-07 已删除**）：该脚本在受限终端下定位 uv/node 频繁失败，维护成本高于收益；环境初始化回归本节 §3 的显式命令，脚本目录只保留 `build_release.ps1` 与 `smoke.py`
- [x] 打包分发流水线（2026-09-07）：`packaging/app.py` + `packaging/app.spec`（PyInstaller onedir，前端 dist 外置于 exe 同级）+ `scripts/build_release.ps1` 一键脚本（前端构建 → PyInstaller → 组装 voice-system/ → zip → 清理中间产物）；`server/main.py` 新增冻结环境探测，打包态从 exe 同级挂载 web/dist；`pyinstaller` 入 dev 依赖组；已手动验证通过

待完成：

- [ ] `scripts/download_models.py` 模型下载脚本（暂缓，待拓展功能环境配置时再补）
- [x] 1.4 开题交付物第一项（2026-09-06）：开题报告按模板重新生成并交付 `prod/report_work/开题报告（第14组）.docx`；正文 1999 字（节1/2/3/4 = 309/366/664/660），三项拓展功能在第 3 节研究内容中全部覆盖；架构框图嵌入第 4 节，6 篇参考文献；表头学号/专业位留「（待补）」待用户手工补填（已知限制）
- [x] 1.4 可运行的系统原型（2026-09-07）：随打包分发流水线一并完成并验证
- [ ] 1.4 其余交付物：架构设计说明书（报告与 PPT 类未显式要求不列入待办，见第 9 节规则）
- [x] 阶段二功能开发（2026-09-07）：采集（设备/声道/WS 电平/定时停止）、显示（波形缩放选区/频谱/语谱图/信息卡）、处理（淡入淡出/谱减降噪/效果链/历史撤销/A-B 对比）、播放（流端点 + 播放器条），测试 46 项 + 冒烟脚本
- [ ] 阶段三拓展功能（3.1 语音克隆 / 3.2 录音质量检测 / 3.3 语音加噪与降噪）

### 阶段二补充约定

- 播放改由前端 `<audio>` 承担，后端 `sd.play` 保留为退路（ADR 0007）
- 效果产物带血统：`source_id`（上一版）+ `steps`（从源头起的全部步骤）。
  处理历史读 `steps`，撤销就是跳回 `source_id` 指向的句柄——不覆盖、不删除，
  因此撤销不会破坏别人正在对比的音频
- 新增效果仍然只改 `server/core/effects/` + 一行 import；这次没破例

**重建提醒**

- 效果函数必须纯函数；注册表用 `get_type_hints` 解析参数模型，效果文件里不要用 `from __future__ import annotations`
- 前端所有请求走 `/api/...` 相对路径，网络代码只写在 `web/src/api.ts`；源码一律 TypeScript（ADR 0005）

---

## 12. 变更日志

| 日期 | 改动 | 作者 |
|---|---|---|
| 2026-09-02 | 初始化项目：技术选型、架构设计、目录骨架、契约层、基础效果、项目文档 | 组长 |
| 2026-09-02 | 补完服务入口与三个路由模块、频谱分析、Vue 前端工程；测试 27 项通过；修复注册表参数模型解析失败与定时录音取不到数据两个缺陷 | 组长 |
| 2026-09-02 | 清除全部具体代码（先提交备份快照 `1c6e868`），保留并完善架构：各模块目录补 README；Git 规范新增「每次改动后必须及时提交」硬性约束 | zahiko |
| 2026-09-02 | 前端技术栈由「原生 JS」改为 TypeScript（ADR 0005）；默认分支明确为 `master`；同步更新 web/README 与 PLAN.md | zahiko |
| 2026-09-02 | 契约层落地：`server/schemas.py`（含新增 `AudioStatsResponse`，修正旧实现 stats 返回裸 dict 的问题）与 `server/session_store.py`（audio_id 句柄仓库）；ruff 与冒烟验证通过，提交 `d81bd10` | zahiko |
| 2026-09-02 | 调整 Git 规范：默认直接在 `master` 提交，取消「不直接提交」与「合并前至少一人过目」约束，开发分支改为可选 | zahiko |
| 2026-09-02 | 完成 1.3 接口骨架：恢复快照 `1c6e868` 实现并适配新契约层（stats 返回 `AudioStatsResponse`、ruff 修复、测试重构 29 项全过）；Vue 3 + TS 前端工程落位，build 通过；真实麦克风全链路联调验证（录音→波形→播放→效果→下载→dist 托管→Vite 代理） | zahiko |
| 2026-09-02 | 录音质量优化：默认采样率 16k → 48k（前后端同步），InputStream 显式 `blocksize=0` + `latency="low"`；零契约变更，提交 `14fe30b` | zahiko |
| 2026-09-02 | 1.2 收尾：`scripts/setup.ps1` 一键环境脚本落位（uv/node 支持常见安装路径回退定位，规避受限终端 PATH 解析失败；EAP=Stop 下 stderr 重定向误抛已处理）；`download_models.py` 暂缓 | zahiko |
| 2026-09-02 | 1.4 开题报告初稿：按模板生成 `prod/开题报告（第14组）.docx`（选题依据 346 / 研究现状 378 / 研究内容 577 / 技术路线 697 字，含架构框图与 6 篇参考文献）；`pyproject` 新增 `prod` 依赖组（python-docx / pymupdf，仅文档生成用）；进度文件同步 | zahiko |
| 2026-09-06 | 拓展功能范围确定：在语音克隆基础上新增「录音质量检测」（音量过轻 / 疑似爆音 / 环境噪声嘈杂度评估与重录建议）与「语音加噪与降噪」（可调信噪比加噪 + 谱减法降噪闭环验证）两项，共三项必做；PLAN.md 阶段三同步拆分为 3.1–3.5 | zahiko |
| 2026-09-06 | 1.4 开题报告重做：依模板重新生成 `prod/report_work/开题报告（第14组）.docx`，正文 1999 字（节1/2/3/4 = 309/366/664/660，满足下限），表头姓名三行（学号/专业留「（待补）」由作者手工补）、题目与指导教师已填、☑1 工程技术 / ☑3 软件、第 4 节嵌入架构框图（`arch_diagram.png`，1724×1180 @300dpi）与图注；6 篇参考文献；`fill_report.py` 复现脚本（lxml 树级操作）；ruff check . 通过 | zahiko |
| 2026-09-07 | 打包分发：`packaging/app.py` + `app.spec`（PyInstaller onedir，uvicorn 动态加载模块显式声明，前端 dist 外置）+ `scripts/build_release.ps1` 一键脚本（前端构建→打包→组装 voice-system/ + start.bat + 使用说明→zip→清理中间产物）；`server/main.py` 冻结环境探测（exe 同级挂载 web/dist）；pyinstaller 入 dev 组；.gitignore 增 release/、build/；node 定位支持 NODE_EXE 覆盖与多布局回退，npm.cmd 失败自动降级 node+npm-cli.js。用户系统终端手动验证通过；新增交付物规则：报告与 PPT 未显式要求不列入待办 | zahiko |
| 2026-09-07 | 阶段二功能开发（分四次提交）：① 采集——`/api/audio/devices` 设备枚举与选择、单/双声道、`/ws/record` 20Hz 电平推送、无麦 503 容错 ② 显示——`POST /api/analysis/spectrogram`（dB 量化 uint8 下发）、波形缩放/框选/平移/定位、trim 与 fade 效果器、AudioInfo 信息卡 ③ 处理——denoise 谱减法、`/api/effects/chain`、`/api/effects/undo`、`/api/effects/{id}/history`、血统字段 source_id/steps、EffectChainPanel 与 HistoryPanel ④ 播放——`/api/audio/{id}/stream` + PlayerBar（进度/暂停/倍速/A-B 对比，ADR 0007）+ `scripts/smoke.py` 冒烟脚本；测试 29 → 46 项 | zahiko |
| 2026-09-07 | 删除 `scripts/setup.ps1`：受限终端下定位 uv/node 频繁失败，维护成本高于收益；环境初始化回归 AGENT.md §3 显式命令。同步清理 PLAN.md / AGENT.md / `docs/architecture.md` / `build_release.ps1` 注释中的引用（历史 session 日志与变更日志保持原样，不作改写） | zahiko |
