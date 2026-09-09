"""通用音频解码/转码——所有上传入口共用的唯一实现。

设计：
- soundfile(libsndfile) 主路径：wav/mp3/flac/ogg/opus/aiff 原生可解；
  VBR mp3 尾部超帧（错误码 29）用分块读取容错。
- ffmpeg 兜底：m4a/aac/wma/webm 等 libsndfile 解不动的容器。
  管道直解优先；mp4 系容器 moov-at-end 时管道不可 seek（或返回 0 帧空音频
  但退出码为 0），自动退临时文件输入重试。
- 输出统一 float32（值域 [-1,1]）+ 原生采样率；调用方用 encode_wav 落盘，
  实现「任何格式上传 → 统一转 WAV」。

被两个独立进程使用：
- 主干 server（uv 环境）：/api/audio/upload 的解码入口。
- 适配层 services/clone（独立 venv）：参考音频上传的唯一解码入口。

本模块只依赖 numpy + soundfile，不引入任何 Web 框架，两边环境均可安装。
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import BinaryIO

import numpy as np
import soundfile as sf

# 上传受理的音频扩展名（无扩展名的文件跳过预检，直接按内容解码）。
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".wav", ".mp3", ".flac", ".ogg", ".oga", ".opus", ".aif", ".aiff",
     ".m4a", ".m4b", ".aac", ".wma", ".webm"}
)

_BLOCK_FRAMES = 65536


class CodecError(ValueError):
    """音频解码失败。调用方映射为 400/415。"""


# ffmpeg 查找顺序：环境变量 → GPT-SoVITS 整合包内置 → 系统 PATH。
# import 时固化一次；找不到则 m4a/wma 等格式给出可操作的报错信息。
_FFMPEG_ENV = os.environ.get("CLONE_FFMPEG", "")
_ENGINE_DIR = os.environ.get("CLONE_ENGINE_DIR", r"C:\Users\zahi\.venvs\GPT-SoVITS-v2pro-20250604")
FFMPEG_PATH: str | None = next(
    (
        str(p)
        for p in (
            Path(_FFMPEG_ENV) if _FFMPEG_ENV else None,
            Path(_ENGINE_DIR) / "runtime" / "bin" / "ffmpeg.exe",
            Path(_ENGINE_DIR) / "runtime" / "Library" / "bin" / "ffmpeg.exe",
            Path(_ENGINE_DIR) / "ffmpeg.exe",
        )
        if p and p.is_file()
    ),
    None,
) or shutil.which("ffmpeg")


def _read_blockwise(source: BinaryIO) -> tuple[np.ndarray, int]:
    """分块解码，尾部解码失败时保留已成功解码的数据。

    VBR mp3 等格式头部声明的总帧数常大于实际可解码帧数，
    一次性 sf.read 读到尾部会抛 LibsndfileError（错误码 29，
    错误消息为空，表现为 "Unspecified internal error"）。
    """
    with sf.SoundFile(source) as handle:
        sample_rate = int(handle.samplerate)
        chunks: list[np.ndarray] = []
        while True:
            try:
                block = handle.read(_BLOCK_FRAMES, dtype="float32", always_2d=True)
            except sf.LibsndfileError:
                if not chunks:
                    raise
                break
            if block.size == 0:
                break
            chunks.append(block)
    data = chunks[0] if len(chunks) == 1 else np.concatenate(chunks, axis=0)
    return np.asarray(data, dtype=np.float32), sample_rate


def _decode_with_ffmpeg(data: bytes) -> tuple[np.ndarray, int]:
    """soundfile 解不动的格式交给 ffmpeg 解码，返回 always_2d float32。"""
    if not FFMPEG_PATH:
        raise CodecError(
            "该格式需要 ffmpeg 解码但未找到 ffmpeg；"
            "请安装 ffmpeg，或设置环境变量 CLONE_FFMPEG 指向其可执行文件路径"
        )
    base = [FFMPEG_PATH, "-nostdin", "-hide_banner", "-loglevel", "error"]
    output_args = ["-vn", "-map_metadata", "-1", "-c:a", "pcm_s16le", "-f", "wav", "pipe:1"]

    proc: subprocess.CompletedProcess[bytes] | None = None
    decoded: tuple[np.ndarray, int] | None = None
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_input = Path(tmp_dir) / "input.bin"
        tmp_input.write_bytes(data)
        for cmd in (
            [*base, "-i", "pipe:0", *output_args],  # 快路径：管道直解
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
    raise CodecError(f"音频解码失败（ffmpeg）：{detail or '未知错误'}")


def decode_audio(payload: bytes, filename: str = "") -> tuple[np.ndarray, int]:
    """从字节流解码任意受支持格式的音频。

    返回 (float32 数组 always_2d, 采样率)。扩展名在受理名单外时直接拒绝，
    避免把明显不是音频的文件喂给解码器。
    """
    if not payload:
        raise CodecError("上传内容为空")

    ext = Path(filename or "").suffix.lower()
    if ext and ext not in SUPPORTED_EXTENSIONS:
        raise CodecError(
            f"不支持的音频格式 {ext}，支持：wav / mp3 / flac / ogg / opus / "
            f"m4a / aac / wma / webm / aiff"
        )

    source = io.BytesIO(payload)
    try:
        data, sample_rate = sf.read(source, dtype="float32", always_2d=True)
        if data.shape[0] == 0:
            raise CodecError("音频解码结果为空（0 帧）")
        return np.asarray(data, dtype=np.float32), int(sample_rate)
    except Exception:
        # 直接读失败（VBR mp3 尾部超帧 / 非正规封装的 flac / mp4 系容器…）：
        # 优先交给 ffmpeg 干净解码；无 ffmpeg 或 ffmpeg 也失败时退分块读取，
        # 在出错处截断保留已解码部分（历史行为）。全部失败统一 CodecError。
        try:
            return _decode_with_ffmpeg(payload)
        except Exception:
            pass
        source.seek(0)
        try:
            return _read_blockwise(source)
        except Exception as exc:
            raise CodecError(
                f"音频解码失败：文件损坏或格式不受支持"
                f"（{exc.__class__.__name__}）"
            ) from exc


def normalize_extension(filename: str) -> str:
    """上传转换后的展示文件名：非 .wav 扩展名（含无扩展名）统一改为 .wav。

    让「自动转换为 wav」在界面上可见——上传 song.mp3 后列表显示 song.wav。
    """
    path = Path(filename or "")
    if path.suffix.lower() == ".wav":
        return filename
    return path.stem + ".wav" if path.stem else filename


def encode_wav(data: np.ndarray, sample_rate: int, subtype: str = "PCM_16") -> bytes:
    """把 float32 数组编码为 WAV 字节流。"""
    buffer = io.BytesIO()
    sf.write(
        buffer,
        np.asarray(data, dtype=np.float32),
        int(sample_rate),
        subtype=subtype,
        format="WAV",
    )
    return buffer.getvalue()
