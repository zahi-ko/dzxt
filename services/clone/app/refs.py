"""参考音频仓库：落盘、校验、索引、删除。

设计约束：
- 音频文件写为 WAV 后存放在 wavs/，文件名即 ref_id，永不重命名——
  引擎合成时需要的是引擎本机可读的绝对路径，路径一旦入索引就视为稳定。
- 索引持久化为 wavs/refs.json（JSON + 写锁）。数据量小，不值得上 sqlite；
  重启后从文件恢复，参考音不因适配层重启而丢失。
"""

from __future__ import annotations

import io
import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import soundfile as sf

from app.config import REF_MAX_SEC, REF_MIN_SEC, WAVS_DIR


class RefError(ValueError):
    """参考音频校验失败（对映 HTTP 400）。"""


@dataclass
class RefRecord:
    ref_id: str
    filename: str
    duration: float
    sample_rate: int
    channels: int
    prompt_text: str
    created_at: str


@dataclass
class RefStore:
    """线程安全的参考音频仓库，单例运行于适配层进程内。"""

    directory: Path = WAVS_DIR
    _loaded: bool = field(default=False, init=False)
    _index: dict[str, RefRecord] = field(default_factory=dict, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    @property
    def _index_path(self) -> Path:
        return self.directory / "refs.json"

    def _load(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self._index_path.exists():
            return
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return  # 索引损坏时不阻塞启动，视为空仓库
        for item in raw:
            try:
                record = RefRecord(**item)
            except TypeError:
                continue
            if (self.directory / f"{record.ref_id}.wav").exists():
                self._index[record.ref_id] = record

    def ensure_loaded(self) -> None:
        with self._lock:
            if not self._loaded:
                self._load()
                self._loaded = True

    def _save(self) -> None:
        payload = [asdict(r) for r in self._index.values()]
        self._index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add(self, data: bytes, filename: str, prompt_text: str = "") -> RefRecord:
        """校验并落盘一份参考音频，返回元数据。"""
        if not data:
            raise RefError("上传内容为空")

        try:
            wav, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        except Exception as exc:  # soundfile 对损坏/不支持格式的异常类型不稳定
            raise RefError(
                "音频解码失败：参考音频请使用 WAV（也接受 mp3/flac），其余格式请先转换"
            ) from exc

        duration = float(wav.shape[0]) / float(sr)
        if duration < REF_MIN_SEC or duration > REF_MAX_SEC:
            raise RefError(
                f"参考音频时长 {duration:.1f}s 超出受理范围 "
                f"({REF_MIN_SEC:.0f}–{REF_MAX_SEC:.0f}s，建议 5–10s 清晰人声)"
            )

        ref_id = uuid.uuid4().hex[:12]
        self.directory.mkdir(parents=True, exist_ok=True)
        sf.write(self.directory / f"{ref_id}.wav", wav, sr, subtype="PCM_16")

        record = RefRecord(
            ref_id=ref_id,
            filename=filename or f"{ref_id}.wav",
            duration=round(duration, 3),
            sample_rate=int(sr),
            channels=int(wav.shape[1]),
            prompt_text=prompt_text.strip(),
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        with self._lock:
            self._index[ref_id] = record
            self._save()
        return record

    def list(self) -> list[RefRecord]:
        self.ensure_loaded()
        with self._lock:
            return sorted(self._index.values(), key=lambda r: r.created_at)

    def get(self, ref_id: str) -> RefRecord:
        self.ensure_loaded()
        with self._lock:
            record = self._index.get(ref_id)
        if record is None:
            raise KeyError(f"参考音频不存在: {ref_id}")
        return record

    def path_of(self, ref_id: str) -> str:
        """引擎本机可读的绝对路径（引擎与适配层同机部署）。"""
        self.get(ref_id)
        return str((self.directory / f"{ref_id}.wav").resolve())

    def update_prompt(self, ref_id: str, prompt_text: str) -> RefRecord:
        self.ensure_loaded()
        with self._lock:
            record = self._index.get(ref_id)
            if record is None:
                raise KeyError(f"参考音频不存在: {ref_id}")
            record.prompt_text = prompt_text.strip()
            self._save()
            return record

    def delete(self, ref_id: str) -> None:
        self.ensure_loaded()
        with self._lock:
            if self._index.pop(ref_id, None) is None:
                raise KeyError(f"参考音频不存在: {ref_id}")
            self._save()
        try:
            (self.directory / f"{ref_id}.wav").unlink(missing_ok=True)
        except OSError:
            # 索引已删，物理文件删除失败仅留下孤儿文件，不影响功能正确性
            pass

    def count(self) -> int:
        return len(self.list())
