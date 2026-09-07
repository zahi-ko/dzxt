"""Core 层纯函数测试。

效果器全部是无副作用的纯函数，因此这里不需要任何 mock，
也是整套系统里最容易保证正确性的部分。
"""

from __future__ import annotations

import numpy as np
import pytest

import server.core.effects  # noqa: F401  触发效果器注册
from server.core.analysis.spectrogram import quantize_db, stft_magnitude_db
from server.core.analysis.spectrum import average_spectrum, waveform_envelope
from server.core.registry import apply_effect, get_effect, list_effects

SR = 16000


def tone(seconds: float = 1.0, freq: float = 440.0, sr: int = SR) -> np.ndarray:
    t = np.linspace(0, seconds, int(seconds * sr), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_registry_is_not_empty() -> None:
    names = {item.name for item in list_effects()}
    assert {"reverse", "gain", "tempo_resample", "tempo_ola", "normalize"} <= names


def test_effect_info_carries_params_schema() -> None:
    info = next(item for item in list_effects() if item.name == "gain")
    assert "db" in info.params_schema["properties"]


def test_reverse() -> None:
    x = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
    out = apply_effect("reverse", x, SR)
    np.testing.assert_allclose(out, x[::-1])


def test_gain_applies_decibel_scale() -> None:
    # 6 dB 对幅度是 10^(6/20) ≈ 1.9953 倍，不是 2 倍；2 倍对应约 6.0206 dB
    x = tone(0.2)
    out = apply_effect("gain", x, SR, {"db": 6.0})
    np.testing.assert_allclose(out, x * 10.0 ** (6.0 / 20.0), rtol=1e-5)


def test_gain_at_20db_is_tenfold() -> None:
    x = np.full(16, 0.05, dtype=np.float32)  # 0.05 * 10 = 0.5，不会触发限幅
    out = apply_effect("gain", x, SR, {"db": 20.0})
    np.testing.assert_allclose(out, x * 10.0, rtol=1e-5)


def test_normalize_reaches_target_peak() -> None:
    x = tone(0.5)
    out = apply_effect("normalize", x, SR, {"peak_db": -6.0})
    np.testing.assert_allclose(np.max(np.abs(out)), 10 ** (-6 / 20), rtol=1e-4)


def test_tempo_resample_changes_duration() -> None:
    x = tone(1.0)
    out = apply_effect("tempo_resample", x, SR, {"speed": 2.0})
    assert out.shape[0] == pytest.approx(x.shape[0] / 2, rel=0.02)


def test_tempo_ola_changes_duration() -> None:
    x = tone(1.0)
    out = apply_effect("tempo_ola", x, SR, {"speed": 2.0})
    assert out.shape[0] < x.shape[0] * 0.7
    assert out.shape[0] > x.shape[0] * 0.3


def test_output_is_always_clipped_and_float32() -> None:
    x = tone(0.5)
    out = apply_effect("gain", x, SR, {"db": 24.0})
    assert out.dtype == np.float32
    assert np.max(np.abs(out)) <= 1.0


def test_unknown_effect_raises() -> None:
    with pytest.raises(KeyError):
        apply_effect("does_not_exist", tone(0.1), SR)


def test_invalid_params_raise_validation_error() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        apply_effect("gain", tone(0.1), SR, {"db": 999})


def test_effect_definition_exposes_title() -> None:
    assert get_effect("reverse").title == "倒放"


def test_waveform_envelope_has_fixed_point_count() -> None:
    x = tone(5.0)
    minimum, maximum = waveform_envelope(x, points=300)
    assert len(minimum) == 300
    assert len(maximum) == 300
    assert all(lo <= hi for lo, hi in zip(minimum, maximum))


def test_average_spectrum_shape() -> None:
    x = tone(1.0)
    freqs, magnitude_db = average_spectrum(x, SR, n_fft=1024)
    assert freqs.shape == magnitude_db.shape
    assert len(freqs) == 1024 // 2 + 1


def test_average_spectrum_peaks_at_tone_frequency() -> None:
    x = tone(1.0, freq=1000.0)
    freqs, magnitude_db = average_spectrum(x, SR, n_fft=2048)
    peak_index = int(np.argmax(magnitude_db))
    assert freqs[peak_index] == pytest.approx(1000.0, abs=20.0)


# ---------- 阶段二新增：裁剪 / 淡入淡出 / 降噪 / 语谱图 ----------


def test_trim_cuts_selected_range() -> None:
    x = tone(2.0)
    out = apply_effect("trim", x, SR, {"start_sec": 0.5, "end_sec": 1.0})
    assert out.shape[0] == pytest.approx(int(0.5 * SR), rel=0.01)


def test_trim_with_zero_end_goes_to_tail() -> None:
    x = tone(2.0)
    out = apply_effect("trim", x, SR, {"start_sec": 1.5, "end_sec": 0.0})
    assert out.shape[0] == pytest.approx(int(0.5 * SR), rel=0.01)


def test_fade_edges_go_to_zero_and_middle_unchanged() -> None:
    x = np.ones(SR, dtype=np.float32) * 0.5
    out = apply_effect("fade", x, SR, {"fade_in": 0.1, "fade_out": 0.1})

    assert out[0] == pytest.approx(0.0, abs=1e-6)
    assert out[-1] == pytest.approx(0.0, abs=1e-6)
    assert out[SR // 2] == pytest.approx(0.5, abs=1e-6)


def test_denoise_preserves_length_and_improves_snr() -> None:
    # 类语音激励：谐波串 + 停顿，模拟音节间隙
    rng = np.random.default_rng(0)
    length = SR * 2
    t = np.arange(length) / SR
    env = ((np.arange(length) // int(0.15 * SR)) % 2 == 0).astype(np.float32)
    clean = np.zeros(length, dtype=np.float32)
    for harmonic in (1, 2, 3, 5):
        clean += (0.25 / harmonic) * np.sin(2 * np.pi * 300 * harmonic * t).astype(np.float32)
    clean = (clean * env).astype(np.float32)
    noisy = np.clip(clean + 0.08 * rng.standard_normal(length), -1, 1).astype(np.float32)

    def snr(reference: np.ndarray, actual: np.ndarray) -> float:
        residual = float(np.sum((reference - actual) ** 2))
        return 10 * np.log10(float(np.sum(reference**2)) / max(residual, 1e-12))

    out = apply_effect("denoise", noisy, SR, {"strength": 1.0})
    assert out.shape[0] == noisy.shape[0]
    assert snr(clean, out) > snr(clean, noisy)


def test_denoise_handles_stereo() -> None:
    x = np.stack([tone(0.5), tone(0.5, freq=880.0)], axis=1)
    out = apply_effect("denoise", x, SR, {"strength": 1.0})
    assert out.ndim == 2
    assert out.shape == x.shape


def test_spectrogram_shape_and_quantization() -> None:
    magnitude_db, times, freqs = stft_magnitude_db(tone(1.0), SR, n_fft=512, max_frames=200)
    assert magnitude_db.shape[1] == 512 // 2 + 1
    assert magnitude_db.shape[0] <= 200
    assert len(times) == magnitude_db.shape[0]
    assert len(freqs) == magnitude_db.shape[1]

    quantized = quantize_db(magnitude_db, -80.0, 0.0)
    assert quantized.dtype == np.uint8
    assert quantized.min() >= 0 and quantized.max() <= 255
