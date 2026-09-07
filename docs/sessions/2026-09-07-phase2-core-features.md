# 2026-09-07 · 阶段二（中期）功能开发

## 本次做了什么

按 PLAN.md 2.1 → 2.5 顺序推进，共四次提交（`3f99c32` → `f767f85` → `e00861b` → 90a8aa4）。

### 2.1 采集

| 项 | 落点 |
|---|---|
| 设备枚举与选择 | `GET /api/audio/devices`，`list_input_devices()` 过滤 `max_input_channels > 0` |
| 采样率 / 声道 | `RecordStartRequest` 加 `channels`（1/2）、`device`；前端下拉 16k/44.1k/48k |
| 实时电平 | `WS /ws/record`，录音中 20Hz、空闲 1Hz；前端 WS 优先、失败自动退轮询 |
| 无麦容错 | `DeviceError` 统一收敛 PortAudio 异常 → HTTP 503 + 中文提示，服务不崩 |
| 定时停止 | 已有 `threading.Timer` 实现，本次确认可用 |

### 2.2 显示

- `POST /api/analysis/spectrogram`：STFT 幅度谱 dB 量化成 **uint8 一维数组**下发，
  前端用 `ImageData` 直接贴 Canvas（频率轴翻转，低频在下）。480×257 ≈ 12 万字节，
  比浮点矩阵小一个量级且免解析。
- 波形：滚轮缩放（以指针为锚点）/ 拖动框选 / Shift 拖动平移 / 单击定位 / 双击全览 /
  播放指针；时间刻度随缩放自适应。
- 新增 `AudioInfo` 信息卡：时长、采样率、声道、样本数、RMS、峰值（含 dBFS）。
- 顺带落了 `trim` 与 `fade` 效果器，让「选区」有实际出口（裁剪选区按钮）。

### 2.3 处理

- `denoise`：分位数噪声估计 + 谱减法 + 保留原相位 ISTFT。
- `AudioEntry` 加 `source_id` / `steps` 血统字段；`SessionStore.root_of()` 上溯链条起点。
- `POST /api/effects/chain`：一次请求串多步，只产出一个句柄，历史逐步可查。
- `POST /api/effects/undo`：跳回上一版句柄，**不覆盖不删除**。
- `GET /api/effects/{id}/history`：链条起点 + 全部步骤。
- 前端：抽出 `EffectParamsFields` 共用表单；新增 `EffectChainPanel`、`HistoryPanel`。

### 2.4 播放

- `GET /api/audio/{id}/stream`（inline WAV）；播放改由前端 `<audio>` 承担 → **ADR 0007**。
- `PlayerBar`：播放/暂停/停止、可拖动进度条 + 实时指针、0.5–2× 倍速、
  与处理前原始音频的 A/B 同位置切换对比。
- 列表「播放」统一走播放器，避免两套播放状态不同步。

### 2.5 工程质量

- 测试 29 → **46 项**（新增 trim/fade/denoise/语谱图纯函数 + 设备/效果链/历史/撤销/流接口）。
- `scripts/smoke.py`：端到端冒烟（采集→显示→处理→历史→播放/导出），已写入 AGENT.md 提交前清单。

## 遗留问题与坑

1. **真实麦克风未验证**：沙盒环境调不动音频设备，后端链路靠冒烟脚本覆盖。
   需在本机跑一遍 `uv run python -m server.main` + `npm run dev`，确认录音、设备下拉、
   WS 电平三条都通。
2. **谱减法的固有边界**：对持续单频正弦会把信号当噪声削掉（实测 SNR 从 9 dB 掉到 0.06 dB）。
   类语音信号（含停顿的谐波串）则提升 2.5–3.5 dB。局限已写进 `denoise.py` docstring，
   答辩要主动讲。真要改善得换成最小值追踪（minimum statistics），暂时不做。
3. **撤销依赖父句柄还在**：父句柄被删会返回 409 并提示。若要更稳，需要存快照，
   代价是内存与复杂度，暂不做。
4. **`scripts/setup.ps1` 处于已删除未提交状态**（非本次改动，开工前就存在）。
   本次提交未带它，需要用户决定恢复还是正式删除并补 scripts/README。
5. `web/dist` 已重新构建，重新打包 release 时记得跑 `scripts/build_release.ps1`。

## 下一个 session 从哪里接手

阶段三拓展功能，建议顺序：

1. **3.2 录音质量检测**（最省事、纯算法）：`server/core/analysis/quality.py`，
   算 RMS/峰值判定音量过轻、削波比例判定爆音、无声段底噪估计判定环境嘈杂，
   综合出「建议重录 / 合格」。前端在录音完成后弹结果。
2. **3.3 语音加噪与降噪**：加噪效果器（可调 SNR 白噪）+ 复用现有 denoise，
   做加噪→降噪闭环并量化 SNR 变化。
3. **3.1 语音克隆**（门槛最高，放最后）：`services/clone/` 独立环境 + GPT-SoVITS。

开工前先读 `AGENT.md` 第 11 节（已更新到中期完成状态）与 `PLAN.md` 阶段三。
