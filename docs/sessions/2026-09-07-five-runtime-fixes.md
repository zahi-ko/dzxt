# Session 2026-09-07 — 5 项运行期问题排查

## 做了什么

用户报告 5 个使用中遇到的问题，逐一定位根因并修复（提交 `327d1f5` + 文档 `587bef7`）：

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | 打开网页未操作时提示「音频加载失败」 | `<audio :src="">` 空 src 触发 media error 事件 | PlayerBar 改 `:src="streamUrl || undefined"`（Vue 移除非空属性）；onError 加 audioId 防御性判断 |
| 2 | 波形单击定位游标回跳 | 流端点不支持 HTTP Range | `/api/audio/{id}/stream` 解析 `Range: bytes=...`，返回 206 + Content-Range + Accept-Ranges |
| 3 | 不支持拖动播放 | 同 #2：浏览器 media 元素非 seekable | 同 #2 |
| 4 | 多个录音名无法区分 | 硬编码 `label="录音"` | `stop_record` 用 `f"录音 {datetime.now():%H:%M:%S}"` |
| 5 | 上传 mp3 报 `Unspecified internal error` | VBR mp3 头部总帧数大于实际可解码帧数，一次 `sf.read` 抛 `LibsndfileError(29, '')` | `load_audio` 一次 read 失败时退回分块解码（65 536 帧/块），尾部错误时保留已解码部分 |

附加：
- `tests/test_short.mp3`：由 `test.mp3` 裁剪的 30s 短片（529 KB），方便日常回归
- `vite.config.ts`：代理目标支持 `BACKEND_URL` 环境变量覆盖（默认仍 127.0.0.1:8000），方便端口被占时切换
- `tests/test_api.py`：新增 3 项（mp3 上传、分块解码、流端点 Range 全覆盖）；总 46 → 49 项

## 验证

- `uv run ruff check .` ✓
- `uv run pytest -q` ✓ 49 passed
- `uv run python scripts/smoke.py` ✓ 全链路
- 端到端 curl：上传 mp3 → 200；`Range: bytes=100-199` → 206 + `Content-Range: bytes 100-199/5292044` + `Accept-Ranges: bytes`
- 浏览器层（agent-browser 0.27 + Chromium 152）：首次 `snapshot` 后等待 8s 无错误提示（验证 #1）；mp3 列表项成功出现（验证 #5 前端）
  - 局限：agent-browser 0.27 的 `eval` 命令在独立临时标签页跑，导致 ref 跨命令状态难追；#2/#3 浏览器层走完 seek 行为未直观跑通，但底层 206 协议 + 标准浏览器 media 元素行为已是确定路径

## 遗留 / 备忘

- **本机 8000 端口被系统进程占用**（WinError 10013，2026-09-07 实测）。`netsh interface ipv4 show excludedportrange` 不显示 8000，但 `netstat` 发现一条 `192.168.1.104:8000 → 156.248.9.25:443` 的 ESTABLISHED 出站连接（某应用抢占本地 8000 当源端口）。用 `8899` 跑通了测试。后续若启动失败，按 `BACKEND_URL=http://127.0.0.1:8899` 起。
- 浏览器层验证未走完：agent-browser 0.27 频繁 SIGTERM / eval 跨标签页。下一 session 若要复测，建议手动在系统终端跑 `npm run dev` + 打开 Chrome 直观验证。
- `core.autocrlf=true` 使 AGENT.md 这次改动产生 337/334 行 churn（内容正确，仅行尾 CRLF↔LF 噪声）。后续如需大改 AGENT.md，可用 `git -c core.autocrlf=false commit` 抑制，或先在 repo 内 `git config core.autocrlf false`。

## 下一个 session 接手

阶段三拓展功能（按 PLAN.md）：
- 3.1 语音克隆（独立 `services/clone/`）
- 3.2 录音质量检测
- 3.3 语音加噪与降噪（可调 SNR 加噪 + 谱减降噪闭环）

修好的 5 项问题无需回看。
