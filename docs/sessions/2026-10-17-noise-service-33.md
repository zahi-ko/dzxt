# 2026-10-17 · 立体声 500 修复 + 3.3 语音加噪与降噪：独立子服务落地

## 本次做了什么

1. **立体声 500 修复**（用户报：调用「不变调变速」「淡入淡出」internal server error）：
   - 根因：`tempo_ola` 的 `out[pos:pos+frame] += segment` 遇 `(frame, 2)` 段与
     一维 out 无法广播；`fade` 的 `out[:n] *= ramp` 同理（末维 2 vs n 不匹配）。
     单声道不受影响，所以既有测试全绿——只有立体声输入（如 mp3 上传）触发。
   - 修复：OLA 抽出 `_ola_channel`，立体声逐通道处理后 `np.stack(axis=1)`
     （对齐 denoise 既有模式）；fade 的 ramp 按 `(-1, 1)` reshape 后再广播。
   - 回归测试 3 项：`test_tempo_ola_handles_stereo`（含通道一致性断言）、
     `test_fade_handles_stereo`、`test_apply_stereo_only_effects_via_api`
     （API 级复刻 500 路径，注意 `np.stack` 要 `axis=1`，否则 soundfile 报
     LibsndfileError——2×8000 被当成 2 帧 8000 声道）。

2. **3.3 语音加噪与降噪改制为独立子服务**（ADR 0008，用户四点要求）：
   - 移除效果器注册表原 `denoise`（文件 / 注册 import / 两个测试 / smoke 引用）。
   - 新建仓库外项目 `C:\Users\zahi\Desktop\noise-service`：**独立 git（master，
     初始提交已 GPG 签名）+ 独立 venv（Python 3.11，uv sync）**，与 dzxt 零共享。
     架构对齐 clone 适配层：`main.py` + `app/{dsp,audio,schemas,config}.py` +
     README + 测试 29 项。DSP 核心 = 用户提供的 n1.py 原样封装（加噪[白/粉/布朗，
     可调 SNR] / 谱减降噪 / SNR 评估）；立体声在服务层逐通道分发并保留声道数。
   - 主干接入：`server/noise_provider.py`（NoiseProvider ABC + LocalAdapterProvider，
     trust_env=False 防代理劫持；None 参数不进表单避免 int 字段 422）+
     `api/routers/noise.py`（`/api/noise/status|operations|process|snr`；
     process 产物带血统 `source_id`/`steps` 入库，撤销与 A/B 对比天然成立）+
     schemas.py 五个 noise 模型 + main.py 注册路由 + tests/test_noise.py 13 项。
   - **实测联调**（服务真起、走真实 HTTP）：加噪命中目标 5.00 dB；降噪后
     SNR 5.00 → 13.52 dB；立体声 channels=2 保留；history/undo 正常。

3. **文档**：ADR 0008；AGENT.md §2/§3.5/§11/§12；PLAN.md 2.3 注记 + 3.3 重写；
   architecture.md §1.1 拓扑/§2 模块表/§7.3 重写。

4. **提交**（master，均 GPG 签名）：`f6e7207` 立体声修复 + denoise 移除；
   `81b8378` 主干接入。测试 88 → 101 项全过，ruff 与冒烟通过。

## 遗留问题与坑

- **沙盒 gpg 签名**：Git Bash 自带 gpg 的 keyboxd 起不来
  （`/usr/lib/gnupg/keyboxd` 报 probably not installed，但 exe 实际存在）。
  解法：手动 `keyboxd.exe --daemon` 拉起守护后 gpg 即恢复，`git commit -S`
  可过（用户密钥 `0F54D966CF8E3004` 在 ~/.gnupg）。若 keyboxd 再挂，
  按用户指示可不签名提交。
- **表单 None 值**：multipart 传 `noise_frames=None` 会被 httpx 序列化成
  空串，FastAPI 解析 int|None 直接 422。provider 侧已过滤 None（用服务默认值）。
- noise-service 只支持 libsndfile 可读格式（WAV/FLAC/OGG）；主干上传已统一
  转 WAV，正常链路无感知。mp3 直传服务会 415。
- dzxt 侧 smoke.py 效果链的 denoise 步骤已改为 gain → normalize。

## 下一个 session 从哪里接手

- **前端「加噪降噪」面板**（PLAN 3.3 剩余项）：App 底部「开发中」卡片替换为
  真实面板——`GET /api/noise/operations` 动态生成参数表单（schemaToFields 已有）、
  `/api/noise/process` 处理回流试听、`/api/noise/snr` 做闭环对比展示。
  api.ts 增对应方法（唯一后端耦合点）。
- 3.2 录音质量检测仍全部未开始（architecture.md §7.2 已有接入方案）。
- start.bat 可按需追加 noise-service 启动行（当前未加，避免强依赖）。

---

## 【2026-10-18 修订】子服务迁入仓库内 services/noise

用户新指令：「像 clone 一样接入 services」。位置决策修订（ADR 0008 已加修订记录）：

- `C:\Users\zahi\Desktop\noise-service` → `services/noise/`（mv，内容全保留）。
- 删除独立 `.git`：原仓库仅 1 个本地初始提交（7f75e5b）、无 remote，工作树
  内容即全部资产；源码自此随 dzxt git 管理（主干一次 commit 覆盖迁移）。
- 独立 venv 保留但需重建：旧 venv 迁移后 `uv run` 报
  "Failed to canonicalize script path"（script path 缓存失效），
  `rm -rf .venv && uv sync` 后恢复；直调 `.venv\Scripts\python.exe -m pytest`
  在迁移当时仍可用（29 项全过）。
- 主干侧代码零契约改动（HTTP 接口未变），仅 `routers/noise.py` 离线提示
  改指 `services/noise`；文档同步：AGENT.md §2/§3.5/目录树/§6/§11/§12、
  ADR 0008 修订记录、architecture.md §1.1 ASCII 图/§7.3、PLAN.md、服务 README。
