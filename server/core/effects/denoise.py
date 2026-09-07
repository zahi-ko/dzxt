"""简易降噪：谱减法（Spectral Subtraction）。

原理（答辩口径）：
1. 假设噪声是准平稳的，且比语音弱——取每个频点在所有时帧上的低分位数
   （默认 10%）作为该频点的噪声幅度估计，比"取开头 N 帧"更鲁棒，
   不依赖端点检测，也不会因为开头正好是语音而失效。
2. 从带噪幅度谱中减去 α·噪声谱，得到语音幅度谱估计：
       |X̂| = max(|X| − α·|N|, β·|N|)
   其中 α 为过减因子，β 为噪声地板（防止减成负数产生"音乐噪声"）。
3. 保留原相位，用估计幅度重构复数谱，再做 ISTFT 重叠相加还原时域。

局限（答辩要主动讲，不要等老师问）：
1. 单通道方法，无法利用空间信息，对非平稳噪声（突然的键盘声、关门声）效果有限。
2. 稳态单音与稳态噪声在短时谱上不可区分——若输入是持续不变的单频信号，
   噪声估计会把它也当成噪声削弱。实测：类语音信号（含停顿的谐波串）SNR
   提升约 2.5–3.5 dB；持续单频正弦反而会变差，属于该算法的固有边界。
3. 过减因子调大能压掉更多噪声，但会引入"音乐噪声"，floor_gain 就是用来兜底的。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from server.core.registry import register_effect

N_FFT = 1024
HOP = 256


def _spectral_subtract_channel(
    x: np.ndarray,
    strength: float,
    floor_gain: float,
    noise_percentile: float,
) -> np.ndarray:
    window = np.hanning(N_FFT).astype(np.float32)
    padded = np.pad(x, (N_FFT, N_FFT), mode="constant")
    frames = np.lib.stride_tricks.sliding_window_view(padded, N_FFT)[::HOP]
    if frames.shape[0] == 0:
        return x.copy()

    spectra = np.fft.rfft(frames * window, axis=1)
    magnitude = np.abs(spectra)

    noise = np.percentile(magnitude, noise_percentile, axis=0).astype(np.float32)
    cleaned = np.maximum(magnitude - strength * noise, floor_gain * noise)

    # 幅度收缩比例乘回原谱：等价于保留原相位只改幅度
    gain = cleaned / (magnitude + 1e-9)
    enhanced = spectra * gain

    return _istft(enhanced, window, x.shape[0])


def _istft(spectra: np.ndarray, window: np.ndarray, length: int) -> np.ndarray:
    """重叠相加还原时域，按窗函数和归一化消除幅度起伏。"""
    n_frames = spectra.shape[0]
    out_len = (n_frames - 1) * HOP + N_FFT
    out = np.zeros(out_len, dtype=np.float64)
    weight = np.zeros(out_len, dtype=np.float64)

    for index in range(n_frames):
        start = index * HOP
        out[start : start + N_FFT] += np.fft.irfft(spectra[index]) * window
        weight[start : start + N_FFT] += window

    np.maximum(weight, 1e-6, out=weight)
    restored = (out / weight)[N_FFT : N_FFT + length]
    return restored.astype(np.float32)


class DenoiseParams(BaseModel):
    strength: float = Field(default=1.0, ge=0.0, le=4.0, description="过减因子 α，越大降噪越狠")
    floor_gain: float = Field(
        default=0.02, ge=0.0, le=0.5, description="噪声地板 β，抑制残留的音乐噪声"
    )
    noise_percentile: float = Field(
        default=10.0, ge=1.0, le=50.0, description="噪声估计分位数，越小噪声估得越低"
    )


@register_effect(
    name="denoise",
    title="降噪（谱减法）",
    description="估计噪声谱并从带噪谱中减去，保留原相位还原时域",
)
def denoise(x: np.ndarray, sr: int, params: DenoiseParams) -> np.ndarray:
    if x.size == 0:
        return x.copy()

    if x.ndim == 1:
        return _spectral_subtract_channel(
            x, params.strength, params.floor_gain, params.noise_percentile
        )

    channels = [
        _spectral_subtract_channel(
            np.ascontiguousarray(x[:, channel]),
            params.strength,
            params.floor_gain,
            params.noise_percentile,
        )
        for channel in range(x.shape[1])
    ]
    return np.stack(channels, axis=1)
