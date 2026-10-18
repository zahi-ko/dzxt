"""谱减法（Spectral Subtraction）语音加噪 / 降噪核心算法。

本模块是纯函数库：输入输出都是 float32 ndarray（单声道一维，值域 [-1, 1]），
不做任何 I/O、不碰全局状态。立体声的分发与 WAV 编解码在 app/audio.py。

算法来源：用户提供的 n1.py（谱减法语音加噪 / 降噪模块），
封装为子服务时保持算法与默认值原样，便于答辩口径统一。

主要接口
--------
add_noise(x, snr_db, noise_type)      -> 加噪
spectral_subtract(x, sr, ...)         -> 谱减法降噪
estimate_snr(clean, noisy)            -> 计算实际信噪比(dB)
"""

from __future__ import annotations

import numpy as np

__all__ = ["add_noise", "spectral_subtract", "denoise", "estimate_snr"]


# ============================================================
#  基础工具
# ============================================================

def _as_float32_mono(x) -> np.ndarray:
    """统一成 float32 单通道一维数组，并夹紧到 [-1, 1]。"""
    x = np.asarray(x)
    if x.ndim == 2:
        if 1 in x.shape:
            x = x.reshape(-1)
        else:                      # 多通道 -> 单通道
            x = x.mean(axis=1)
    elif x.ndim > 2:
        raise ValueError(f"不支持的输入维度: {x.shape}")
    x = np.ascontiguousarray(x, dtype=np.float32)
    return np.clip(x, -1.0, 1.0)


def _frame(x: np.ndarray, frame_len: int, hop: int):
    """分帧。返回 (frames[num_frames, frame_len], 原始长度)。"""
    n = len(x)
    if n == 0:
        return np.zeros((0, frame_len), dtype=np.float64), 0

    if n < frame_len:
        num_frames = 1
        padded = np.pad(x, (0, frame_len - n))
    else:
        num_frames = 1 + (n - frame_len + hop - 1) // hop      # ceil
        padded_len = (num_frames - 1) * hop + frame_len
        padded = np.pad(x, (0, max(0, padded_len - n)))

    idx = np.arange(frame_len)[None, :] + hop * np.arange(num_frames)[:, None]
    return padded[idx], n


def _overlap_add(frames: np.ndarray, hop: int, out_len: int) -> np.ndarray:
    """重叠相加。"""
    frame_len = frames.shape[1]
    total = (frames.shape[0] - 1) * hop + frame_len
    out = np.zeros(total, dtype=np.float64)
    for i in range(frames.shape[0]):
        out[i * hop: i * hop + frame_len] += frames[i]
    return out[:out_len]


def _pink_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    """1/f 粉红噪声（幅度谱 ∝ 1/sqrt(f)）。"""
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    f = np.arange(spec.size, dtype=np.float64)
    f[0] = 1.0
    spec = spec / np.sqrt(f)
    spec[0] = 0.0
    noise = np.fft.irfft(spec, n=n)
    s = np.std(noise)
    return noise / s if s > 0 else noise


def _brown_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    """1/f^2 布朗（红）噪声。"""
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    f = np.arange(spec.size, dtype=np.float64)
    f[0] = 1.0
    spec = spec / f
    spec[0] = 0.0
    noise = np.fft.irfft(spec, n=n)
    s = np.std(noise)
    return noise / s if s > 0 else noise


# ============================================================
#  1. 加噪
# ============================================================

def add_noise(x, snr_db: float = 10.0, noise_type: str = "white", seed=None) -> np.ndarray:
    """
    给语音加噪。

    Parameters
    ----------
    x : np.ndarray[float32], 值域 [-1, 1]
        干净语音。
    snr_db : float
        目标信噪比(dB)。越大越干净。
    noise_type : {'white', 'pink', 'brown'}
        噪声类型。
    seed : int | None
        随机种子，便于复现。

    Returns
    -------
    y : np.ndarray[float32], 值域 [-1, 1]
        带噪语音。
    """
    x = _as_float32_mono(x)
    n = x.size
    if n == 0:
        return x.copy()

    rng = np.random.default_rng(seed)
    noise_type = noise_type.lower()

    if noise_type == "white":
        noise = rng.standard_normal(n)
    elif noise_type == "pink":
        noise = _pink_noise(n, rng)
    elif noise_type in ("brown", "red", "brownian"):
        noise = _brown_noise(n, rng)
    else:
        raise ValueError(f"未知噪声类型: {noise_type!r}，可选 'white'/'pink'/'brown'")

    noise = noise.astype(np.float64)
    xf = x.astype(np.float64)

    sig_pow = float(np.mean(xf ** 2))
    if sig_pow <= 1e-12:                      # 全静音，直接返回
        return x.copy()

    noise_pow = float(np.mean(noise ** 2))
    target_pow = sig_pow / (10.0 ** (snr_db / 10.0))
    noise *= np.sqrt(target_pow / max(noise_pow, 1e-20))

    y = xf + noise

    # 保持值域 [-1, 1]：优先整体缩放（不改变 SNR），再兜底 clip
    peak = float(np.max(np.abs(y)))
    if peak > 1.0:
        y = y * (0.999 / peak)

    return np.clip(y, -1.0, 1.0).astype(np.float32)


# ============================================================
#  2. 谱减法降噪
# ============================================================

def spectral_subtract(x,
                      sr: int = 16000,
                      frame_ms: float = 25.0,
                      hop_ms: float = 10.0,
                      alpha: float = 2.0,
                      beta: float = 0.02,
                      noise_est_ratio: float = 0.15,
                      noise_frames: int | None = None,
                      gain_smooth: float = 0.5) -> np.ndarray:
    """
    基于谱减法的语音降噪。

    原理
    ----
    1. 分帧 + 加窗 + STFT，得到幅度谱 |X| 与相位 ∠X；
    2. 估计噪声功率谱 Pn（默认取能量最低的若干帧做平均）；
    3. 谱减：  Py = max(|X|^2 - alpha * Pn,  beta * Pn)
    4. 保留原始相位重建：Y = sqrt(Py) * exp(j∠X)
    5. IFFT + 重叠相加 + 窗归一化。

    Parameters
    ----------
    x : np.ndarray[float32], 值域 [-1, 1]
        带噪语音。
    sr : int
        采样率。
    frame_ms, hop_ms : float
        帧长 / 帧移（毫秒），默认 25ms / 10ms。
    alpha : float
        过减因子。越大降噪越狠，但语音失真和“音乐噪声”越明显。
        常用 1.5 ~ 3.0。
    beta : float
        谱底系数（噪声残留下限），防止谱减过度产生空洞。
        常用 0.001 ~ 0.05。
    noise_est_ratio : float
        噪声估计时取能量最低的帧比例（0~1）。默认 0.15。
    noise_frames : int | None
        若给定，则直接用前 N 帧作为纯噪声段估计噪声谱；
        为 None 时使用 noise_est_ratio 的自适应方式。
    gain_smooth : float
        增益在时间轴上的一阶平滑系数（0~1）。0 表示不平滑。
        适度平滑可抑制“音乐噪声”。

    Returns
    -------
    y : np.ndarray[float32], 值域 [-1, 1]
        降噪后的语音。
    """
    x = _as_float32_mono(x)
    n = x.size
    if n == 0:
        return x.copy()

    # ---- 参数准备 ----
    frame_len = int(round(sr * frame_ms / 1000.0))
    hop = int(round(sr * hop_ms / 1000.0))
    n_fft = 1
    while n_fft < frame_len:
        n_fft <<= 1
    frame_len = n_fft
    hop = max(1, min(hop, frame_len))

    win = np.hamming(frame_len).astype(np.float64)

    # ---- 分帧 + STFT ----
    frames, orig_len = _frame(x.astype(np.float64), frame_len, hop)
    n_frames = frames.shape[0]
    if n_frames == 0:
        return x.copy()

    spec = np.fft.rfft(frames * win, n=n_fft, axis=1)      # [F, K]
    mag = np.abs(spec)
    power = mag ** 2
    phase = spec / (mag + 1e-12)                           # 单位相位

    # ---- 噪声功率谱估计 ----
    if noise_frames is not None and noise_frames > 0:
        k = min(int(noise_frames), n_frames)
        noise_power = power[:k].mean(axis=0)
    else:
        frame_energy = power.sum(axis=1)
        k = int(np.ceil(noise_est_ratio * n_frames))
        k = max(1, min(k, n_frames))
        idx = np.argsort(frame_energy)[:k]                 # 能量最小的 k 帧
        noise_power = power[idx].mean(axis=0)

    noise_power = np.maximum(noise_power, 1e-12)

    # ---- 谱减 ----
    power_out = np.maximum(power - alpha * noise_power, beta * noise_power)
    mag_out = np.sqrt(power_out)

    # ---- 增益平滑（抑制音乐噪声）----
    if gain_smooth and gain_smooth > 0.0 and n_frames > 1:
        gain = mag_out / (mag + 1e-12)
        sm = np.empty_like(gain)
        sm[0] = gain[0]
        c = float(np.clip(gain_smooth, 0.0, 0.99))
        for i in range(1, n_frames):
            sm[i] = c * sm[i - 1] + (1.0 - c) * gain[i]
        mag_out = sm * mag

    # ---- 用原始相位重建 ----
    spec_out = mag_out * phase
    frames_out = np.fft.irfft(spec_out, n=n_fft, axis=1)

    # ---- 合成加窗 + 加权重叠相加 ----
    frames_out *= win
    wsum_frames = np.tile(win ** 2, (n_frames, 1))
    y = _overlap_add(frames_out, hop, orig_len)
    wsum = _overlap_add(wsum_frames, hop, orig_len)
    y = y / np.maximum(wsum, 1e-8)

    return np.clip(y, -1.0, 1.0).astype(np.float32)


# 语义化别名
denoise = spectral_subtract


# ============================================================
#  3. 辅助：实际信噪比
# ============================================================

def estimate_snr(clean, noisy) -> float:
    """计算 noisy 相对 clean 的实际 SNR(dB)。两者需等长且同量纲。"""
    clean = np.asarray(clean, dtype=np.float64).reshape(-1)
    noisy = np.asarray(noisy, dtype=np.float64).reshape(-1)
    m = min(clean.size, noisy.size)
    clean, noisy = clean[:m], noisy[:m]

    ps = float(np.mean(clean ** 2))
    pn = float(np.mean((noisy - clean) ** 2))
    if pn <= 1e-20:
        return float("inf")
    return 10.0 * np.log10(ps / pn + 1e-20)
