"""参考音频仓库：落盘、校验、索引、删除。

设计约束：
- 上传支持多格式（wav/mp3/flac/ogg/opus/m4a/aac/wma/webm/aiff），
  soundfile 主路径解码，ffmpeg 兜底；最终统一转写为 WAV(PCM_16) 存放于
  wavs/，文件名即 ref_id，永不重命名——
  引擎合成时需要的是引擎本机可读的绝对路径，路径一旦入索引就视为稳定。
- 索引持久化为 wavs/refs.json（JSON + 写锁）。数据量小，不值得上 sqlite；
  重启后从文件恢复，参考音不因适配层重启而丢失。
"""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import soundfile as sf

from app.config import FFMPEG_PATH, REF_MAX_SEC, REF_MIN_SEC, SUPPORTED_EXTENSIONS, WAVS_DIR


class RefError(ValueError):
    """参考音频校验失败（对映 HTTP 400）。"""


_FORMAT_HINT = "wav / mp3 / flac / ogg / opus / m4a / aac / wma / webm / aiff"


def _decode_with_ffmpeg(data: bytes) -> tuple[Any, int]:
    """soundfile 解不动的格式（m4a/aac/wma/webm…）交给 ffmpeg 解码。

    快路径走管道不落临时文件；失败（如 mp4 系容器 moov 在文件尾、
    管道不可 seek）自动退临时文件输入重试，兼容各 ffmpeg 版本行为差异。
    """
    if not FFMPEG_PATH:
        raise RefError(
            f"该格式需要 ffmpeg 解码但未找到 ffmpeg，"
            f"可安装 ffmpeg 或设置环境变量 CLONE_FFMPEG 指向其路径"
        )
    base = [FFMPEG_PATH, "-nostdin", "-hide_banner", "-loglevel", "error"]
    output_args = ["-vn", "-map_metadata", "-1", "-c:a", "pcm_s16le", "-f", "wav", "pipe:1"]

    proc: subprocess.CompletedProcess[bytes] | None = None
    decoded: tuple[Any, int] | None = None
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_input = Path(tmp_dir) / "input.bin"
        tmp_input.write_bytes(data)
        for cmd in (
            [*base, "-i", "pipe:0", *output_args],       # 快路径：管道直解
            [*base, "-i", str(tmp_input), *output_args],  # 兜底：可 seek 的文件输入
        ):
            proc = subprocess.run(cmd, input=data, capture_output=True)
            if proc.returncode != 0 or not proc.stdout:
                continue
            candidate = sf.read(io.BytesIO(proc.stdout), dtype="float32", always_2d=True)
            # mp4 系容器经管道输入可能返回 0 帧空音频（moov 不可达但退出码为 0），
            # 必须按失败处理，继续走文件输入兜底
            if candidate[0].shape[0] > 0:
                decoded = candidate
                break

    if decoded is not None:
        return decoded
    detail = (proc.stderr if proc else b"").decode("utf-8", "replace").strip()[:200]
    raise RefError(f"音频解码失败（ffmpeg）：{detail or '未知错误'}")


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
        """校验并落盘一份参考音频，返回元数据。

        解码策略：soundfile 原生解 wav/mp3/flac/ogg/opus/aiff；
        解不动的（m4a/aac/wma/webm…）退 ffmpeg。最终统一以 PCM_16 WAV
        落盘，引擎侧永远只面对 wav，无需感知上传格式。
        """
        if not data:
            raise RefError("上传内容为空")

        ext = Path(filename or "").suffix.lower()
        if ext and ext not in SUPPORTED_EXTENSIONS:
            raise RefError(
                f"不支持的音频格式 {ext or '(无扩展名)'}，"
                f"支持：{_FORMAT_HINT}"
            )

        try:
            wav, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        except Exception:
            # soundfile 不识别的格式/扩展名谎报，交给 ffmpeg 兜底
            wav, sr = _decode_with_ffmpeg(data)

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
