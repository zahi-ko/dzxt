"""音频文件读写。统一转换为 float32，值域 [-1, 1]。"""

from __future__ import annotations

import io

import numpy as np
import soundfile as sf


def load_audio(payload: bytes) -> tuple[np.ndarray, int]:
    """从字节流解码音频，返回 (float32 数组, 采样率)。"""
    data, sample_rate = sf.read(io.BytesIO(payload), dtype="float32", always_2d=False)
    return np.asarray(data, dtype=np.float32), int(sample_rate)


def dump_audio(data: np.ndarray, sample_rate: int, subtype: str = "PCM_16") -> bytes:
    """把 float32 数组编码为 WAV 字节流。"""
    buffer = io.BytesIO()
    sf.write(buffer, np.asarray(data, dtype=np.float32), sample_rate, subtype=subtype, format="WAV")
    return buffer.getvalue()
