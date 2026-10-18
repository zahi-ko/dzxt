"""WAV 字节编解码与声道分发。

服务边界只传 WAV 字节（与 clone 适配层的 multipart 风格一致，
不违反主干「模块间不传 WAV bytes」的铁律——那条铁律约束的是主干内部模块）。
内部一律 float32 ndarray，值域 [-1, 1]。

立体声逐通道处理、声道数原样保留：谱减的噪声估计与加噪的噪声叠加
都不能像 gain 那样直接广播窗函数/噪声向量（dzxt 曾在此栽过 500）。
"""

from __future__ import annotations

import io

import numpy as np
import soundfile as sf

from app.dsp import add_noise, spectral_subtract

ENCODE_SUBTYPE = "PCM_16"


def decode_wav(payload: bytes) -> tuple[np.ndarray, int]:
    """WAV 字节 → (float32 ndarray, sample_rate)。单声道 (n,)，立体声 (n, ch)。"""
    try:
        data, sr = sf.read(io.BytesIO(payload), dtype="float32", always_2d=False)
    except Exception as exc:
        raise ValueError(f"音频解码失败（仅支持 libsndfile 可读的格式，推荐 WAV）：{exc}") from exc
    if data.size == 0:
        raise ValueError("音频内容为空")
    return np.ascontiguousarray(data, dtype=np.float32), int(sr)


def encode_wav(data: np.ndarray, sample_rate: int) -> bytes:
    """ndarray → WAV 字节（PCM_16，与主干上传解码精度一致）。"""
    buffer = io.BytesIO()
    sf.write(
        buffer,
        np.asarray(data, dtype=np.float32),
        int(sample_rate),
        format="WAV",
        subtype=ENCODE_SUBTYPE,
    )
    return buffer.getvalue()


def channels_of(x: np.ndarray) -> int:
    return 1 if x.ndim == 1 else x.shape[1]


def add_noise_audio(
    x: np.ndarray,
    sr: int,
    snr_db: float,
    noise_type: str,
    seed: int | None,
) -> np.ndarray:
    """加噪。立体声逐通道独立施噪——seed 按声道偏移，保证可复现且声道间不相关。"""
    if x.ndim == 1:
        return add_noise(x, snr_db=snr_db, noise_type=noise_type, seed=seed)

    channels = []
    for index in range(x.shape[1]):
        channel_seed = None if seed is None else seed + index
        channels.append(
            add_noise(
                np.ascontiguousarray(x[:, index]),
                snr_db=snr_db,
                noise_type=noise_type,
                seed=channel_seed,
            )
        )
    return np.stack(channels, axis=1)


def denoise_audio(x: np.ndarray, sr: int, **params) -> np.ndarray:
    """谱减降噪。立体声逐通道估计噪声谱（各声道噪声独立）。"""
    if x.ndim == 1:
        return spectral_subtract(x, sr=sr, **params)

    channels = [
        spectral_subtract(np.ascontiguousarray(x[:, index]), sr=sr, **params)
        for index in range(x.shape[1])
    ]
    return np.stack(channels, axis=1)
