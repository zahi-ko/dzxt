# ADR 0008: 语音加噪与降噪改制为独立子服务

**日期**：2026-10-17
**状态**：已接受
**相关**：ADR 0006（拓展范围）、ADR 0004（克隆子服务先例）、AGENT.md §3.5、docs/architecture.md §7.3

## 背景

ADR 0006 将「语音加噪与降噪」定为三项必做拓展之一，原计划按效果器铁律三
以 `server/core/effects/noise_add.py` / `noise_reduce.py` 接入（阶段二曾以
`denoise` 效果器形式落地过简易谱减）。2026-10-17 用户提出新约束：

1. 移除效果器注册表中的原有降噪功能；
2. 将加噪/降噪算法（用户提供的 n1.py 谱减法模块）封装为**独立服务**，
   与语音克隆（services/clone）的组织方式对齐；
3. 新服务必须**独立虚拟环境**，且**不与当前项目（dzxt）共享 git**；
4. 若无法独立，则只提供 README，后续在新工作空间按 README 开发。

## 决策

**3.3 语音加噪与降噪从「效果器注册表内实现」改为「独立子服务 + 主干 Provider 对接」。**

- 新服务 `noise-service`：位于 dzxt 仓库**之外**
  （`C:\Users\zahi\Desktop\noise-service`），**独立 git 仓库 + 独立 venv**
  （Python 3.11），FastAPI 无状态服务，端口 9910。
  【2026-10-18 修订】迁入 dzxt 仓库内 `services/noise/`，与 `services/clone`
  同组织模式：独立 venv 保留，独立 git 撤销（源码随 dzxt git 管理），
  修订理由见文末「修订记录」。
- 架构对齐克隆子服务先例（ADR 0004 的适配层模式）：
  主干经 `NoiseProvider` 抽象层（`server/noise_provider.py`）以 HTTP 对接，
  子服务离线时主干返回 503 / `online=false`，不拖垮基础功能。
- DSP 核心（`app/dsp.py`）= n1.py 原样封装：可调 SNR 加噪（白/粉/布朗）、
  谱减法降噪、SNR 评估；立体声在服务层逐通道分发。
- 主干侧接口：`/api/noise/status`、`/api/noise/operations`、
  `/api/noise/process`（产物带血统入库，可撤销）、`/api/noise/snr`（闭环验证）。
- 移除 `server/core/effects/denoise.py` 及其注册、测试与 smoke 引用。

## 理由

- **用户明确要求独立 venv + 独立 git**：服务放在仓库内即使加 .gitignore
  也与当前项目共享工作树，嵌套 git 仓库亦是隐患；仓库外独立项目是
  「不与当前项目共享 git」最彻底的履约方式（与克隆引擎位于仓库外同构）。
  【2026-10-18 修订】用户随后要求「像 clone 一样接入 services」——即接受
  仓库内共享 git，换取与 `services/clone` 一致的运维模式（单一仓库克隆、
  统一提交签名、目录内自包含）。独立 venv 的隔离目标不受影响，仍满足
  「不共享依赖环境」的初衷。
- **复用克隆子服务验证过的模式**：Provider 抽象 + 离线降级 + trust_env=False，
  路由与前端零侵入；ADR 0004 的「云端插槽」思路同样适用
  （换 Provider 子类即可切换云端实现）。
- **独立演进**：服务自有 git 历史与版本节奏，dzxt 只依赖 HTTP 契约；
  `NOISE_SERVICE_URL` 环境变量即可指向任意部署位置。
- **不影响分发**：克隆子服务本就不参与 PyInstaller 打包（AGENT.md §11），
  本服务同理，主干接口在无服务时优雅降级。

## 后果

- dzxt 侧新增：`server/noise_provider.py`、`server/api/routers/noise.py`、
  schemas.py 五个 noise 模型（契约层改动，需全组同步）、`tests/test_noise.py`。
- 文档同步：AGENT.md §2 / §3.5 / §11 / §12，PLAN.md 3.3，
  docs/architecture.md §7.3 由「注册表效果器」改写为「独立子服务」。
- 前端「加噪降噪」卡片（开发中占位）后续按 `/api/noise/*` 接口开发，
  本 ADR 不含前端实现。
- 若未来需要仓库内复现：按 noise-service/README.md 重新创建即可，
  接口契约以主干 schemas.py 与子服务 app/schemas.py 互为镜像为准。

## 修订记录

| 日期 | 修订 |
|---|---|
| 2026-10-18 | 位置由仓库外独立项目（`C:\Users\zahi\Desktop\noise-service`，独立 git）迁入仓库内 `services/noise/`：用户要求与 `services/clone` 同组织模式。独立 venv（Python 3.11）保留；独立 git 撤销（原仓库仅 1 个本地初始提交、无 remote，工作树内容全部保留）；`.venv` 重建后 `uv run` 恢复。主干侧代码零改动（HTTP 契约未变），仅离线提示与文档路径更新。 |
