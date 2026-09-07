"""PyInstaller 打包入口。

开发态请勿直接运行本文件，开发入口是 `uv run python -m server.main`。
打包由 `packaging/app.spec` 与 `scripts/build_release.ps1` 负责：
前端 dist 外置于 exe 同级目录，由 main.py 的冻结环境探测逻辑挂载。
"""

import uvicorn

import server.main  # noqa: F401  导入即完成路由挂载与效果器注册
from server.main import app

if __name__ == "__main__":
    # 冻结环境下必须传 app 对象：字符串 "server.main:app" 依赖模块路径解析，
    # 在 PyInstaller 中不可用；reload 功能开发态专属，打包后必须关闭。
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
