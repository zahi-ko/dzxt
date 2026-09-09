"""参考音频仓库：落盘、校验、索引、删除、音色打包。

设计约束：
- 上传支持多格式（wav/mp3/flac/ogg/opus/m4a/aac/wma/webm/aiff），
  统一经 common/audio_codec 解码（与主干同一份实现），最终转写为
  WAV(PCM_16) 存放于 wavs/，文件名即 ref_id，永不重命名——
  引擎合成时需要的是引擎本机可读的绝对路径，路径一旦入索引就视为稳定。
- 索引持久化为 wavs/refs.json（JSON + 写锁）。数据量小，不值得上 sqlite；
  重启后从文件恢复，参考音不因适配层重启而丢失。
- 音色可导出/导入 .clone 文件（ZIP 容器：voice.json 元数据 + ref.wav），
  只含参考音频、参考文本、预设合成文本，不含任何模型权重（zero-shot 无需 pth）。
"""

from __future__ import annotations

import json
import re
import threading
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path

from common.audio_codec import CodecError, decode_audio, encode_wav, normalize_extension

from app.config import REF_MAX_SEC, REF_MIN_SEC, WAVS_DIR

CLONE_FORMAT_VERSION = 1
_VOICE_META = "voice.json"
_VOICE_AUDIO = "ref.wav"


class RefError(ValueError):
    """参考音频校验失败（对映 HTTP 400）。"""


def _safe_voice_name(name: str) -> str:
    """从展示文件名提取可入包名/下载名的音色名。"""
    stem = Path(name or "").stem.strip()
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", stem)
    return stem[:40] or "voice"


@dataclass
class RefRecord:
    ref_id: str
    filename: str
    duration: float
    sample_rate: int
    channels: int
    prompt_text: str
    created_at: str
    sample_text: str = ""  # 最近一次为该音色合成的文本；导出 .clone 时打包


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

        解码统一走 common/audio_codec（soundfile 主路径 + ffmpeg 兜底），
        最终以 PCM_16 WAV 落盘，引擎侧永远只面对 wav，无需感知上传格式。
        展示文件名归一为 .wav，让「已自动转换」在界面上可见。
        """
        try:
            wav, sr = decode_audio(data, filename=filename)
        except CodecError as exc:
            raise RefError(str(exc)) from exc

        duration = float(wav.shape[0]) / float(sr)
        if duration < REF_MIN_SEC or duration > REF_MAX_SEC:
            raise RefError(
                f"参考音频时长 {duration:.1f}s 超出受理范围 "
                f"({REF_MIN_SEC:.0f}–{REF_MAX_SEC:.0f}s，建议 5–10s 清晰人声)"
            )

        ref_id = uuid.uuid4().hex[:12]
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{ref_id}.wav").write_bytes(encode_wav(wav, sr))

        record = RefRecord(
            ref_id=ref_id,
            filename=normalize_extension(filename) or f"{ref_id}.wav",
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

    # ---------- 音色打包（.clone） ----------

    def export_clone(self, ref_id: str) -> tuple[bytes, str]:
        """打包为 .clone（ZIP：voice.json + ref.wav），返回 (字节, 建议文件名)。"""
        record = self.get(ref_id)
        wav_path = self.directory / f"{record.ref_id}.wav"
        voice_name = _safe_voice_name(record.filename)
        meta = {
            "format": "dzxt-voice-clone",
            "version": CLONE_FORMAT_VERSION,
            "name": voice_name,
            "prompt_text": record.prompt_text,
            "sample_text": record.sample_text,
            "duration": record.duration,
            "sample_rate": record.sample_rate,
            "created_at": record.created_at,
        }
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(_VOICE_META, json.dumps(meta, ensure_ascii=False, indent=2))
            zf.write(wav_path, _VOICE_AUDIO)
        return buffer.getvalue(), f"{voice_name}.clone"

    def import_clone(self, data: bytes, filename: str = "") -> RefRecord:
        """从 .clone 文件还原音色（参考音频 + 参考文本 + 预设合成文本）。"""
        try:
            with zipfile.ZipFile(BytesIO(data)) as zf:
                names = set(zf.namelist())
                if _VOICE_META not in names or _VOICE_AUDIO not in names:
                    raise RefError(
                        "无效的音色文件：缺少 voice.json 或 ref.wav（需要 .clone 导出文件）"
                    )
                meta = json.loads(zf.read(_VOICE_META).decode("utf-8"))
                if meta.get("format") != "dzxt-voice-clone":
                    raise RefError("无效的音色文件：format 标识不匹配")
                wav_bytes = zf.read(_VOICE_AUDIO)
        except zipfile.BadZipFile as exc:
            raise RefError("无效的音色文件：不是合法的 .clone 包") from exc
        except json.JSONDecodeError as exc:
            raise RefError("无效的音色文件：voice.json 解析失败") from exc

        # 展示名取音色名（.clone 扩展名不能直接进解码预检），归一为 .wav
        voice_name = _safe_voice_name(filename or str(meta.get("name", "")) or "voice")
        record = self.add(
            wav_bytes, f"{voice_name}.wav", str(meta.get("prompt_text", ""))
        )
        sample_text = str(meta.get("sample_text", "")).strip()
        if sample_text:
            record = self.update_sample_text(record.ref_id, sample_text)
        return record

    # ---------- 查询与编辑 ----------

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

    def update_sample_text(self, ref_id: str, sample_text: str) -> RefRecord:
        """记录最近一次为该音色合成的文本（导出 .clone 时随之打包）。"""
        self.ensure_loaded()
        with self._lock:
            record = self._index.get(ref_id)
            if record is None:
                raise KeyError(f"参考音频不存在: {ref_id}")
            record.sample_text = sample_text.strip()
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
