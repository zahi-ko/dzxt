# scripts/ · 打包与冒烟脚本

| 脚本 | 用途 | 用法 |
|---|---|---|
| `smoke.py` | 提交前端到端冒烟：采集 → 显示 → 处理 → 历史 → 播放/导出 | `uv run python scripts/smoke.py` |
| `build_release.ps1` | 一键打包分发：前端构建 → PyInstaller → 组装 `voice-system/` → zip | 在系统终端 `powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1` |

环境初始化不在此处，按 `AGENT.md` §3 的显式命令执行（原 `setup.ps1` 已于 2026-09-07 删除）。

大文件（模型权重、测试音频）禁止入库，一律 `.gitignore` + 本目录脚本下载。
