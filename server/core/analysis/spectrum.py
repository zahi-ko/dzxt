"""频谱与波形分析。

全部为纯函数，输入输出都不含 I/O 副作用。

设计说明：前端画波形时不需要原始采样点——一段 10 秒 48kHz 音频有 48 万个点，
全量传过去既慢又没必要。这里提供包络抽取（min/max），前端用 2000 个点
就能画出视觉上完全等价的波形。
"""

from __future__ import annotations

import numpy as np


def to_mono(x: np.ndarray) -> np.ndarray:
    """多声道转单声道。单声道原样返回。"""
    data = np.asarray(x, dtype=np.float32)
    if data.ndim == 1:
        return data
    return data.mean(axis=1).astype(np.float32)


def average_spectrum(
    x: np.ndarray, sample_rate: int, n_fft: int = 1024
) -> tuple[np.ndarray, np.ndarray]:
    """分段加窗 FFT 后取平均功率谱。

    返回 (频率数组, 幅度 dB 数组)，长度均为 n_fft // 2 + 1。
    整段平均比单帧更能代表整段音频的频谱特征。
    """
    mono = to_mono(x)
    if mono.size < n_fft:
        mono = np.pad(mono, (0, n_fft - mono.size))

    hop = max(1, n_fft // 2)
    window = np.hanning(n_fft).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(mono, n_fft)[::hop]
    if frames.shape[0] == 0:
        frames = mono[:n_fft].reshape(1, n_fft)

    spectra = np.fft.rfft(frames * window, axis=1)
    power = np.mean(np.abs(spectra) ** 2, axis=0)
    magnitude_db = 10.0 * np.log10(power + 1e-12)

    freqs = np.fft.rfftfreq(n_fft, d=1.0 / float(sample_rate))
    return freqs, magnitude_db


def waveform_envelope(
    x: np.ndarray, points: int = 2000
) -> tuple[list[float], list[float]]:
    """抽取波形包络，返回 (每段最小值, 每段最大值)。

    段数固定为 points，因此无论音频多长，返回的数据量恒定。
    """
    mono = to_mono(x)
    if mono.size == 0:
        return [], []

    if mono.size <= points:
        values = mono.astype(float).tolist()
        return values, values

    edges = np.linspace(0, mono.size, points + 1).astype(int)
    minimum: list[float] = []
    maximum: list[float] = []

    for i in range(points):
        segment = mono[edges[i] : edges[i + 1]]
        if segment.size == 0:
            minimum.append(0.0)
            maximum.append(0.0)
        else:
            minimum.append(float(segment.min()))
            maximum.append(float(segment.max()))

    return minimum, maximum


def rms_level(x: np.ndarray) -> float:
    """整体 RMS 电平。"""
    mono = to_mono(x)
    if mono.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(mono**2)))


def peak_level(x: np.ndarray) -> float:
    """峰值电平。"""
    mono = to_mono(x)
    if mono.size == 0:
        return 0.0
    return float(np.max(np.abs(mono)))
