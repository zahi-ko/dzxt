"""语谱图（STFT 热力图）计算。

纯函数，无 I/O。输出量化为 uint8 矩阵供前端直接贴到 Canvas ImageData：
- 浮点矩阵（frames × bins）直接 JSON 序列化体积大且解析慢
- 人眼看热力图根本分辨不出 8bit 以上的灰度层次，量化不损失有效信息

算法要点（答辩可讲）：
1. 分帧加汉宁窗，抑制频谱泄漏
2. rfft 取正频率，幅度转 dB（20·log10）
3. 按时帧在频率轴展开，形成时频二维矩阵
"""

from __future__ import annotations

import numpy as np

from server.core.analysis.spectrum import to_mono

DEFAULT_FLOOR_DB = -80.0
DEFAULT_CEILING_DB = 0.0


def stft_magnitude_db(
    x: np.ndarray,
    sample_rate: int,
    n_fft: int = 512,
    hop: int | None = None,
    max_frames: int = 480,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """计算 STFT 幅度谱（dB）。

    返回 (幅度矩阵 dB[frames, bins], 帧中心时间数组, 频率数组)。
    hop 缺省时由 max_frames 反推，保证长音频也不会产生超大矩阵。
    """
    mono = to_mono(x)
    if mono.size < n_fft:
        mono = np.pad(mono, (0, n_fft - mono.size))

    if hop is None:
        hop = max(n_fft // 4, int(np.ceil(mono.size / max(1, max_frames))))
    hop = max(1, int(hop))

    window = np.hanning(n_fft).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(mono, n_fft)[::hop]
    if frames.shape[0] == 0:
        frames = mono[:n_fft].reshape(1, n_fft)

    spectra = np.fft.rfft(frames * window, axis=1)
    magnitude_db = 20.0 * np.log10(np.abs(spectra) + 1e-12)

    times = (np.arange(frames.shape[0]) * hop + n_fft / 2.0) / float(sample_rate)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / float(sample_rate))
    return magnitude_db.astype(np.float32), times, freqs


def quantize_db(
    magnitude_db: np.ndarray, floor_db: float = DEFAULT_FLOOR_DB, ceiling_db: float = DEFAULT_CEILING_DB
) -> np.ndarray:
    """把 dB 矩阵线性量化到 uint8（0 最弱，255 最强），行优先展平。"""
    span = max(1e-6, ceiling_db - floor_db)
    scaled = (magnitude_db - floor_db) / span * 255.0
    return np.clip(scaled, 0.0, 255.0).astype(np.uint8)
