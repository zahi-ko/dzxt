"""音频会话存储。

对外只暴露 audio_id 句柄，波形本体始终留在后端内存。
好处：接口层永不搬运大数组；处理历史天然可追溯，便于实现撤销链。

扩展点：需要重启恢复时，把存储层换成真正的持久化实现即可，
上层 API 无需任何改动。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from server.schemas import AudioMeta, EffectHistoryItem


@dataclass
class AudioEntry:
    audio_id: str
    data: np.ndarray  # float32, 值域 [-1, 1]
    sample_rate: int
    created_at: datetime
    label: str = ""
    # 血统：source_id 指向上一步结果，steps 记录从源头到本品施加过的全部效果。
    # 有了它，「处理历史」「撤销」「A/B 对比基准」都只是读这两个字段。
    source_id: str | None = None
    steps: list[EffectHistoryItem] = field(default_factory=list)

    @property
    def channels(self) -> int:
        return 1 if self.data.ndim == 1 else self.data.shape[1]

    @property
    def duration(self) -> float:
        return float(self.data.shape[0]) / float(self.sample_rate)

    def to_meta(self) -> AudioMeta:
        return AudioMeta(
            audio_id=self.audio_id,
            sample_rate=self.sample_rate,
            channels=self.channels,
            duration=self.duration,
            created_at=self.created_at,
            label=self.label,
        )


class SessionStore:
    """线程安全的音频句柄仓库。"""

    def __init__(self) -> None:
        self._items: dict[str, AudioEntry] = {}
        self._lock = threading.RLock()

    def put(
        self,
        data: np.ndarray,
        sample_rate: int,
        label: str = "",
        source_id: str | None = None,
        steps: list[EffectHistoryItem] | None = None,
    ) -> AudioEntry:
        entry = AudioEntry(
            audio_id=uuid.uuid4().hex[:12],
            data=np.asarray(data, dtype=np.float32),
            sample_rate=int(sample_rate),
            created_at=datetime.now(),
            label=label,
            source_id=source_id,
            steps=list(steps) if steps else [],
        )
        with self._lock:
            self._items[entry.audio_id] = entry
        return entry

    def root_of(self, audio_id: str) -> AudioEntry:
        """沿 source_id 上溯到链条起点（录音或上传的那一版）。"""
        entry = self.get(audio_id)
        seen = {audio_id}
        while entry.source_id and entry.source_id not in seen:
            seen.add(entry.source_id)
            entry = self.get(entry.source_id)
        return entry

    def get(self, audio_id: str) -> AudioEntry:
        with self._lock:
            entry = self._items.get(audio_id)
        if entry is None:
            raise KeyError(f"音频句柄不存在或已释放: {audio_id}")
        return entry

    def list(self) -> list[AudioEntry]:
        with self._lock:
            return sorted(self._items.values(), key=lambda item: item.created_at)

    def delete(self, audio_id: str) -> None:
        with self._lock:
            self._items.pop(audio_id, None)

    def replace(self, audio_id: str, data: np.ndarray, sample_rate: int) -> AudioEntry:
        with self._lock:
            entry = self.get(audio_id)
            entry.data = np.asarray(data, dtype=np.float32)
            entry.sample_rate = int(sample_rate)
        return entry


_STORE = SessionStore()


def get_store() -> SessionStore:
    """全局单例。FastAPI 依赖注入统一走这里。"""
    return _STORE


def monotonic() -> float:
    return time.monotonic()
