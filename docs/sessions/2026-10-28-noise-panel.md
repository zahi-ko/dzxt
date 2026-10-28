# 2026-10-28 · 3.3 前端「加噪降噪」面板

## 本次做了什么

承接 PLAN 3.3 最后一项（前端面板），主干与子服务零改动，纯前端。

1. **契约镜像**（`web/src/api.ts`，唯一后端耦合点）
   - 新增 `NoiseStatusResponse` / `NoiseOperationInfo` / `NoiseOperationListResponse` /
     `NoiseProcessResponse` / `NoiseSnrResponse`，与 `server/schemas.py` 一一对应。
   - 新增方法：`noiseStatus` / `noiseOperations` / `noiseProcess` / `noiseSnr`。
   - `schemaToFields` 升级（效果器与噪声共用同一套动态表单）：
     - `enum` → `FormField.options`，渲染为下拉框；
     - `anyOf: [{type: X}, {type: 'null'}]`（Pydantic v2 的 `X | None`）→ 识别主类型并标
       `nullable`，数字框允许留空；
     - `type: integer` → 步长 1；浮点滑块步长取区间 1% 附近的整齐值
       （`NICE_STEPS`），避免出现 0.65 这类怪步进。
   - 导出共享类型 `ParamValue = number | boolean | string | null`：`null` 语义为「留空」，
     由后端取缺省（`noise_frames` / `seed` 这类可空参数）。

2. **`EffectParamsFields.vue` 增强**（三处面板共用，无破坏性变更）
   - 枚举 → `<select>`，取值文案走 `enumLabel()`（white/pink/brown → 白/粉/布朗噪声，
     未登记的值原样显示，新增操作无需改前端）；
   - 可空数字 → 允许空值，提交 `null`；占位提示「留空即由后端自适应」；
   - `EffectPanel` / `EffectChainPanel` 的本地 `ParamValue` 别名改为从 `api.ts` 导入，
     保证与组件 emit 类型一致。

3. **`NoisePanel.vue`（新）**
   - 顶部服务状态（在线/离线，含 detail tooltip）+ 刷新按钮；
   - 处理对象显示当前选中音频的 label；未选中时提示先选音频；
   - 操作标签页（`/api/noise/operations` 动态生成：加噪 / 谱减降噪）+ 操作说明；
   - 参数表单由该操作的 `params_schema` 生成，切换操作即重置为该操作默认值；
   - 执行按钮受 `audioId`、服务在线、进行中三重约束；
   - **闭环验证区**：基线（clean）/ 对比（noisy）双下拉（选项来自音频列表）+ 计算 SNR +
     对调；处理成功后自动把对比侧指向产物、基线侧取产物血统源头 `root_id`，并立即测一次；
     多次测量结果以列表记录（≥10 dB 标绿）。
   - 产物回流：`applied` 事件交给 App 统一处理（刷新列表 → 选中 → 自动试听），
     抽屉**不关闭**，便于紧接着做 SNR 对比。

4. **`App.vue` 接入**
   - 拓展卡片 03 由「开发中」占位改为可用，带服务状态徽标（`noiseBadge`，`refreshNoiseStatus`
     与克隆状态各自独立拉取）；
   - 抽屉外壳统一：`openDrawer('clone' | 'noise')` / `closeDrawer()` / `drawerTitle`，
     克隆与加噪降噪共用同一套 DOM 与动效，避免复制一整套抽屉；
   - `handleNoiseApplied`：刷新列表 → `playFromLibrary(result.audio_id)` 自动试听。

5. **文档**：`PLAN.md` 3.3 面板项勾选；`AGENT.md` §11 补一条完成项 + §12 变更日志；
   本 session 日志。

## 验收方式（需用户在本机手动跑）

```powershell
# 1) 子服务
cd C:\Users\zahi\Desktop\dzxt\services\noise
.venv\Scripts\python.exe main.py          # 9910

# 2) 后端
cd C:\Users\zahi\Desktop\dzxt
uv run python -m server.main               # 8000

# 3) 前端
cd C:\Users\zahi\Desktop\dzxt\web
npm run dev                                # 5173
```

操作路径：选一条录音 → 底部卡片「03 语音加噪与降噪」→「加噪」5 dB 执行 →
（产物自动播放，SNR 自动算出约 5 dB）→ 切「谱减降噪」执行 →
SNR 升至 13 dB 量级，记录列表两条并列可见。

## 遗留问题与坑

- **类型检查**：`vue-tsc --noEmit` 通过（沙盒内用 `node node_modules/vue-tsc/bin/vue-tsc.js`
  绕过 `.cmd` shim）。`npm run build` 仍由用户手动执行。
- **面板不自动刷新状态**：打开抽屉时探活一次；若先开面板后起子服务，需点「刷新状态」。
- **`noise_type` 展示文案**在 `api.ts` 的 `ENUM_LABELS` 里维护（纯 UI 文案，不参与契约）。
- 参数「留空」统一走 `null`：后端 Pydantic 可空字段接受 `null`；非可空字段不会产生空值
  （默认值来自 Schema），因此不影响既有效果器。

## 下一个 session 从哪里接手

- **3.2 录音质量检测**（阶段三唯一完全空白项）：三项指标（电平过轻 / 削波爆音 / 底噪嘈杂度）
  + 综合评分与重录建议；接入方案见 `docs/architecture.md` §7.2。
- 3.3 剩余「主观听感验证」（答辩演示环节，需人工）。
- 3.4 系统集成：全局异常处理、一键启动脚本（`start.bat` 可考虑加 noise-service）。
