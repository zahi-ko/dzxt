"""语音处理系统 · FastAPI 服务入口。

启动方式（见 AGENT.md）：
    uv run python -m server.main

接口文档自动生成于 http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import server.core.effects  # noqa: F401  导入即触发效果器注册
from server.api.routers import analysis, audio, effects
from server.core.registry import list_effects
from server.schemas import ErrorResponse

app = FastAPI(
    title="语音处理系统",
    description="语音信号采集、处理、显示、播放，以及语音克隆扩展",
    version="0.1.0",
    responses={404: {"model": ErrorResponse}},
)

# 开发态前端跑在 Vite(5173)，需要跨域；生产态由本服务托管 dist，同源访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audio.router)
app.include_router(effects.router)
app.include_router(analysis.router)


@app.get("/api/health", tags=["system"], summary="健康检查")
def health() -> dict:
    return {"status": "ok", "effects": len(list_effects())}


WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_excludes=[".venv/*", "web/node_modules/*", "web/dist/*"],
    )
