# 2026-09-09 · 克隆链路四项优化（默认设备 / 删按钮 / 统一转码 / .clone 打包）

## 需求与落点

1. **采集设备默认「系统默认」**：RecorderCard 不再用后端 default_index 自动选中，
   保持 null = 系统默认；仅在记忆的设备不存在时重置为 null。
2. **删除「保存参考文本」按钮**：参考文本在「上传时填写 + 合成时临时覆盖」
   两个场景已覆盖，持久化按钮无实际价值。PATCH 端点保留（API 契约不动）。
3. **转换无效修复 + 上传预操作统一**：
   - 根因排查：当前适配层代码实测 mp3/m4a/wma/flac 转换全部成功 → 用户侧
     「无效」最可能是适配层进程仍是旧代码（改码后未重启），加上主干上传
     m4a 等格式直接 415、且转换后列表仍显示 .mp3 让人以为没转。
   - 新增 `common/audio_codec.py`：主干与适配层共用同一份解码/编码实现
     （soundfile 主路径 + ffmpeg 兜底 + encode_wav），消灭两处重复实现。
   - 主干 `/api/audio/upload` 覆盖面扩到全部常见格式；两侧上传后展示名
     统一归一为 .wav（转换在 UI 上可见）。
   - 解码策略修正：直接读失败 → **先 ffmpeg**（干净处理 VBR mp3 尾帧、
     坏头 flac、m4a moov-at-end）→ 再分块截断（无 ffmpeg 的历史兜底）。
     实测修复：管道输出的 FLAC 头部声明帧数是垃圾巨值，旧策略走分块
     截断只剩 4.096s（2^17 帧），ffmpeg 路径可干净解出完整 6s。
   - **适配层改码后必须重启**（start.bat 重新双击即可）。
4. **音色 .clone 保存/导入**：
   - 格式：ZIP 容器，`voice.json`（format 标识/version/音色名/参考文本/
     预设合成文本/时长/采样率）+ `ref.wav`。不含 pth——zero-shot 无需权重。
   - 预设合成文本 = 该音色最近一次成功合成的文本（适配层 /synthesize 成功
     后自动记录到 RefRecord.sample_text）。
   - 链路：适配层 GET /refs/{id}/export、POST /refs/import → 主干 Provider
     抽象扩 2 个方法 + 路由代理（UTF-8 Content-Disposition）→ 前端
     「导出音色 (.clone)」blob 下载 + .clone 导入入口 + 选中音色自动预填
     合成文本。
   - 坑：导入时 `.clone` 扩展名会被转码预检拒绝 → 内部落名统一
     `_safe_voice_name(name) + ".wav"`。

## 验证

- pytest 72 → 82 项全过（新增 roundtrip/非法包/导出导入代理与 503/归一化等 10 项）
- ruff 通过；前端 vue-tsc + build 通过
- 适配层端到端复测（TestClient）：mp3/m4a/wma/flac 上传全部 201 + 时长正确

## 遗留

- 用户真机需重启适配层后回归「转换」体验（重点看之前失败的那个文件）。
- PLAN 3.1 余项不变：参考音录制入口、相似度客观指标。

---

## 追加：合成参数扩展 + 记忆式默认参数（同日晚）

- 需求：克隆可自定义配置偏少，要求提供更多设置并括号注明效用；默认参数记忆式（沿用上一次）。
- 引擎侧调研：api_v2 `TTS_Request` 全字段核对（tts_infer.yaml languages = v2 列表）。
- 新增透传参数（适配层 schema → 引擎 payload → 主干 schema/Provider → 前端 api.ts，四层镜像）：
  text_split_method(cut0–cut5)、batch_size、fragment_interval、temperature、top_k、top_p、
  repetition_penalty、seed；默认值与引擎一致，向后兼容。
- 前端：ClonePanel「高级参数」折叠区（11 项，括号注明效用）+「恢复默认参数」；
  localStorage 记忆参数与上次选中参考音（key: dzxt.clone-params.v1 / dzxt.clone-last-ref.v1），
  参考音被删时自动回退到列表首项。
- 测试：主干透传 + 默认兼容（FakeProvider.last_request）、适配层 payload 转发
  （monkeypatch store/engine）。pytest 82 → 85 全过，ruff 过，前端 build 过。

---

## 追加 2：引擎警告「Prompt free is not supported batch_infer」处理（同日更晚）

- 根因定位（读引擎源码）：
  - `TTS.py:1113`：`prompt_text in [None, ""]` → `no_prompt_text=True`（prompt-free 模式）；
  - `TTS.py:1252`：prompt-free 时 `prompt=None` 传入 t2s 模型；
  - `t2s_model.py:596`：`infer_panel_batch_infer` 收到 `prompts=None` → 打印警告并
    自动降级 `infer_panel_naive_batched`。
  - 结论：**警告无害（合成照常成功）**，但 batch_size>1 在无参考文本时完全无效。
- 修复：
  - 适配层 `main.py`：有效参考文本为空 → 强制 `batch_size=1`（不发无效批量）；
  - 前端批大小标签补「仅填写参考文本时生效」；README 参数表同步。
- 顺带修复测试环境依赖：test_clone.py 的 5 个「离线降级」用例依赖 9900 无监听，
  本机适配层运行时被真服务穿透（200/404/400 而非 503）——`client` fixture 改为
  注入 `LocalAdapterProvider(base_url="http://127.0.0.1:1")`，离线路径确定可复现。
- 测试：新增 prompt-free 归一用例；pytest 85 → 86 全过，ruff 过，前端 build 过。

---

## 追加 3：记忆策略分级（同日 21 点）

- 用户需求：高级参数仅本次运行内记忆，重开程序恢复默认；其余参数全部持久记忆。
- 实现（ClonePanel.vue）：
  - 高级参数 11 项：localStorage → **sessionStorage**（同一标签页存活期间含刷新均保持，
    关闭程序即清空，重开恢复默认）；折叠区标题同步注明；
  - 合成文本：从「仅靠 sample_text 自动填充」改为显式持久（localStorage
    `dzxt.clone-last-text.v1`，输入即存、重开沿用）；sample_text 自动填充仍作为
    空文本时的兜底；
  - 参考音选择保持 localStorage；参考文本由后端参考音记录承载（选中即恢复）。
- 前端 build 过，ruff + pytest 86 全过（AGENT.md 预检约定）。

---

## 追加 4：导入音色丢参考文本的根因与修复（同日 21 点）

- 现象：用户导入 .clone 后参考文本为空。
- 排查：适配层 roundtrip 测试通过、导入代码正确；读真实 `wavs/refs.json` 发现
  kobe.wav / audio [vocals].wav 的 prompt_text 全为空——**文本从未入库**。
- 根因：上午按用户要求删掉「保存参考文本」按钮后，编辑框文本只作临时覆盖
  发给引擎，从不持久；导出 .clone 打包记录里的空文本 → 导入无可还原。
- 修复（不恢复按钮，改自动化）：
  ① 前端参考文本编辑框 `@blur` 自动 PATCH 保存（值非空且与记录不同才发），
     就地更新列表项避免重取；
  ② 适配层合成成功后自动回写非空参考文本到记录（文本被合成验证过的时刻
     即持久化时刻，幂等）。
- 测试：新增回写用例（含幂等断言）；pytest 86 → 87 全过，ruff 过，build 过。
- 遗留：用户已导出的旧 .clone 内文本为空无法追溯，需填文本→失焦/合成→重新导出。

---

## 追加 5：克隆面板两处文本命名统一（同日 22 点）

- 用户反馈：「新参考音的文本」与「参考文本」无区分度、不知各自用途。
- 定性：二者本是**同一个引擎参数 `prompt_text`**（GPT-SoVITS 原名 Prompt Text）
  的两个阶段入口——上传时填初始原文，选中后编辑当前参考音的原文。
- 改法（ClonePanel.vue 纯文案，零逻辑）：按引擎原名统一为
  「Prompt Text · 参考音频原文」（上传框 / 编辑框 / promptLang 标签三处）；
  合成文本改「合成文本 Text · 想让音色说的话」，textLang 标签同步；
  合成框上方加一行分工说明（Prompt Text 决定音色，Text 决定产出内容）。
- README 同步旧 UI 名称引用；前端 build 过，ruff + pytest 87 全过。

---

## 追加 6：删除上传时的 Prompt Text 输入框（同日 22 点）

- 用户质疑「一样的东西整两个」：上传框与编辑框确实都是 prompt_text 的入口。
- 复查发现昨晚的改名提交漏改了两个关键标签（上传框仍为「新参考音的文本」、
  编辑框仍为「参考文本」），是用户持续困惑的直接原因。
- 处理：删除上传时的 Prompt Text 输入框及 uploadPrompt 状态，
  api.cloneUploadRef 收敛为单参数（后端 Form prompt_text 默认空串，契约不变）；
  编辑框成为唯一入口，标签改「Prompt Text · 参考音频原文（照抄这段录音里说的话）」，
  合成文本标签补「录音里没有的话，想让 TA 说的新台词」强化对比。
- build / ruff / pytest 87 全过。
