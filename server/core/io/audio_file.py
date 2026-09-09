"""音频文件读写。统一转换为 float32，值域 [-1, 1]。

解码/编码实际实现收敛在 common/audio_codec.py（与克隆适配层共用同一份，
含 ffmpeg 兜底与 VBR mp3 容错）；本模块只维护主干侧的调用契约：
load_audio 保持「单声道返回 1-D 数组」的历史行为，调用方无感。
"""

from __future__ import annotations

import numpy as np

from common.audio_codec import decode_audio, encode_wav


def load_audio(payload: bytes) -> tuple[np.ndarray, int]:
    """从字节流解码音频，返回 (float32 数组, 采样率)。

    兼容历史契约：单声道squeeze为 1-D，多声道保持 2-D。
    支持 wav/mp3/flac/ogg/opus/m4a/aac/wma/webm/aiff（统一入口自动转）。
    """
    data, sample_rate = decode_audio(payload)
    if data.shape[1] == 1:
        return data[:, 0], sample_rate
    return data, sample_rate


def dump_audio(data: np.ndarray, sample_rate: int, subtype: str = "PCM_16") -> bytes:
    """把 float32 数组编码为 WAV 字节流。"""
    return encode_wav(data, sample_rate, subtype=subtype)
