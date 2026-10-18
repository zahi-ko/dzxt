"""DSP 纯函数测试：加噪 / 谱减降噪 / SNR 评估。"""

from __future__ import annotations

import numpy as np
import pytest

from app.dsp import add_noise, estimate_snr, spectral_subtract

SR = 16000


def tone(seconds: float = 1.0, freq: float = 440.0) -> np.ndarray:
    t = np.linspace(0, seconds, int(seconds * SR), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def speech_like(seconds: float = 1.6) -> np.ndarray:
    """类语音激励：谐波串 + 停顿，模拟音节间隙（噪声估计依赖静音段）。"""
    t = np.arange(int(seconds * SR)) / SR
    clean = np.zeros_like(t)
    for f0, amp, s, e in [(200, 0.55, 0.10, 0.45), (320, 0.45, 0.60, 0.95), (160, 0.60, 1.10, 1.50)]:
        mask = (t >= s) & (t < e)
        seg = t[mask] - s
        clean[mask] = amp * np.sin(2 * np.pi * f0 * seg) * np.hanning(mask.sum())
    return (clean * 0.7).astype(np.float32)


# ---------- 加噪 ----------


@pytest.mark.parametrize("snr_db", [10.0, 5.0, 0.0])
def test_add_noise_hits_target_snr(snr_db: float) -> None:
    clean = speech_like()
    noisy = add_noise(clean, snr_db=snr_db, noise_type="white", seed=42)
    assert estimate_snr(clean, noisy) == pytest.approx(snr_db, abs=0.5)


@pytest.mark.parametrize("noise_type", ["white", "pink", "brown"])
def test_add_noise_types_work(noise_type: str) -> None:
    clean = speech_like()
    noisy = add_noise(clean, snr_db=8.0, noise_type=noise_type, seed=0)
    assert noisy.dtype == np.float32
    assert noisy.shape == clean.shape
    assert np.max(np.abs(noisy)) <= 1.0
    # 三种噪声都应让实测 SNR 落在目标附近
    assert estimate_snr(clean, noisy) == pytest.approx(8.0, abs=1.0)


def test_add_noise_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="未知噪声类型"):
        add_noise(tone(0.2), noise_type="blue")


def test_add_noise_seed_is_reproducible() -> None:
    clean = speech_like()
    first = add_noise(clean, snr_db=5.0, seed=7)
    second = add_noise(clean, snr_db=5.0, seed=7)
    np.testing.assert_array_equal(first, second)


def test_add_noise_silent_input_returns_unchanged() -> None:
    silent = np.zeros(SR, dtype=np.float32)
    out = add_noise(silent, snr_db=10.0, seed=1)
    np.testing.assert_array_equal(out, silent)


def test_add_noise_empty_input() -> None:
    out = add_noise(np.zeros(0, dtype=np.float32), snr_db=10.0)
    assert out.size == 0


def test_add_noise_accepts_stereo_by_downmix() -> None:
    """dsp 层按 n1.py 约定把多通道降混为单声道；声道分发在 audio 层。"""
    mono = speech_like(0.5)
    stereo = np.stack([mono, mono * 0.5], axis=1)
    out = add_noise(stereo, snr_db=10.0, seed=3)
    assert out.ndim == 1
    assert out.shape == mono.shape


# ---------- 谱减降噪 ----------


def test_spectral_subtract_improves_snr() -> None:
    clean = speech_like()
    noisy = add_noise(clean, snr_db=5.0, noise_type="white", seed=42)
    out = spectral_subtract(noisy, sr=SR, alpha=2.0, beta=0.02)
    assert out.shape == noisy.shape
    assert estimate_snr(clean, out) > estimate_snr(clean, noisy) + 1.0


def test_spectral_subtract_preserves_length_and_range() -> None:
    noisy = add_noise(tone(1.0), snr_db=5.0, seed=1)
    out = spectral_subtract(noisy, sr=SR)
    assert out.shape == noisy.shape
    assert out.dtype == np.float32
    assert np.max(np.abs(out)) <= 1.0


def test_spectral_subtract_handles_short_input() -> None:
    """短于一帧的信号补零处理，不崩溃、长度不变。"""
    short = tone(0.005)  # 80 samples < 25ms 帧长
    out = spectral_subtract(short, sr=SR)
    assert out.shape == short.shape


def test_spectral_subtract_explicit_noise_frames() -> None:
    clean = speech_like()
    noisy = add_noise(clean, snr_db=5.0, seed=42)
    out = spectral_subtract(noisy, sr=SR, noise_frames=10)
    assert estimate_snr(clean, out) > estimate_snr(clean, noisy)


def test_spectral_subtract_pink_noise() -> None:
    clean = speech_like()
    noisy = add_noise(clean, snr_db=8.0, noise_type="pink", seed=0)
    out = spectral_subtract(noisy, sr=SR)
    assert estimate_snr(clean, out) > estimate_snr(clean, noisy)


def test_spectral_subtract_empty_input() -> None:
    out = spectral_subtract(np.zeros(0, dtype=np.float32), sr=SR)
    assert out.size == 0


# ---------- SNR 评估 ----------


def test_estimate_snr_identical_is_infinite() -> None:
    x = tone(0.2)
    assert estimate_snr(x, x) == float("inf")


def test_estimate_snr_known_value() -> None:
    rng = np.random.default_rng(0)
    clean = tone(0.5)
    noisy = clean + 0.1 * rng.standard_normal(clean.size).astype(np.float32)
    # 用定义独立核算，避免把被测逻辑抄进断言
    noise_power = float(np.mean((noisy - clean) ** 2))
    assert estimate_snr(clean, noisy) == pytest.approx(
        10 * np.log10(float(np.mean(clean**2)) / noise_power), rel=1e-6
    )
