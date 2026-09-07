"""实时推送路由：录音电平 WebSocket。

REST 负责命令，WebSocket 负责实时流（见 AGENT.md 第 7 节）。
前端拿不到麦克风数据，只能靠这里拿到连续电平；没有 WebSocket 时
前端会退回轮询 /api/audio/record/status，功能不降级只是刷新率低一些。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.core.io.device import get_recorder

router = APIRouter(tags=["realtime"])

# 录音中 20Hz 足够顺滑；空闲时降到 1Hz，只为维持连接与状态同步。
ACTIVE_INTERVAL = 0.05
IDLE_INTERVAL = 1.0


@router.websocket("/ws/record")
async def record_level(websocket: WebSocket) -> None:
    await websocket.accept()
    recorder = get_recorder()

    try:
        while True:
            recording = recorder.recording
            payload = {
                "type": "level",
                "recording": recording,
                "elapsed": round(recorder.elapsed, 3),
                "level": round(recorder.level, 5),
                "peak": round(recorder.peak, 5),
            }
            await websocket.send_json(payload)
            await asyncio.sleep(ACTIVE_INTERVAL if recording else IDLE_INTERVAL)
    except WebSocketDisconnect:
        return
    except Exception:  # 连接已断开但框架未抛 WebSocketDisconnect 的情况
        return
