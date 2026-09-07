"""音频文件读写。统一转换为 float32，值域 [-1, 1]。"""

from __future__ import annotations

import io
from typing import BinaryIO

import numpy as np
import soundfile as sf

_BLOCK_FRAMES = 65536


def _read_blockwise(source: BinaryIO) -> tuple[np.ndarray, int]:
    """分块解码，尾部解码失败时保留已成功解码的数据。

    VBR mp3 等格式头部声明的总帧数常大于实际可解码帧数，
    一次性 sf.read 读到尾部会抛 LibsndfileError（错误码 29，
    错误消息为空，表现为 "Unspecified internal error"）。
    分块读取可在出错处截断，而不是丢掉整个文件。
    """
    with sf.SoundFile(source) as handle:
        sample_rate = int(handle.samplerate)
        chunks: list[np.ndarray] = []
        while True:
            try:
                block = handle.read(_BLOCK_FRAMES, dtype="float32", always_2d=False)
            except sf.LibsndfileError:
                if not chunks:
                    raise  # 一帧都没解出来：文件本身不可解码
                break  # 尾部解码失败：接受已解码部分
            if block.size == 0:
                break
            chunks.append(block)
    data = chunks[0] if len(chunks) == 1 else np.concatenate(chunks, axis=0)
    return np.asarray(data, dtype=np.float32), sample_rate


def load_audio(payload: bytes) -> tuple[np.ndarray, int]:
    """从字节流解码音频，返回 (float32 数组, 采样率)。"""
    source = io.BytesIO(payload)
    try:
        data, sample_rate = sf.read(source, dtype="float32", always_2d=False)
    except sf.LibsndfileError:
        # 直接 read 失败时退回分块解码（典型场景：VBR mp3 尾部超帧）
        source.seek(0)
        return _read_blockwise(source)
    return np.asarray(data, dtype=np.float32), int(sample_rate)


def dump_audio(data: np.ndarray, sample_rate: int, subtype: str = "PCM_16") -> bytes:
    """把 float32 数组编码为 WAV 字节流。"""
    buffer = io.BytesIO()
    sf.write(buffer, np.asarray(data, dtype=np.float32), sample_rate, subtype=subtype, format="WAV")
    return buffer.getvalue()
