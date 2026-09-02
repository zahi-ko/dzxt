"""路由层公共依赖。

把「句柄不存在 → 404」这类重复逻辑收在一处，
避免每个 router 各写一遍。
"""

from __future__ import annotations

from fastapi import HTTPException

from server.session_store import AudioEntry, get_store


def require_entry(audio_id: str) -> AudioEntry:
    """按 audio_id 取音频实体，不存在则抛 404。"""
    try:
        return get_store().get(audio_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
