# scripts/ · 环境与下载脚本

- `setup.ps1`：一键环境初始化（前置依赖检查 → 后端 uv sync → 前端 npm install → ruff/pytest 验证）
  用法：`powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`
  麦克风缺失只作温和提示，不中断。
- `download_models.py`（暂缓）：GPT-SoVITS 模型权重下载，待拓展功能环境配置时实现

大文件（模型权重、测试音频）禁止入库，一律 `.gitignore` + 本目录脚本下载。
