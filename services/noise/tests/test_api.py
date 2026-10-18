"""API 冒烟测试：加噪 / 降噪 / SNR 三个端点的请求-响应闭环。"""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient

from main import app

SR = 16000


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def wav_bytes(data: np.ndarray, sr: int = SR) -> bytes:
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, np.asarray(data, dtype=np.float32), sr, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def tone(seconds: float = 1.0, freq: float = 440.0) -> np.ndarray:
    t = np.linspace(0, seconds, int(seconds * SR), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def speech_like(seconds: float = 1.6) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    clean = np.zeros_like(t)
    for f0, amp, s, e in [(200, 0.55, 0.10, 0.45), (320, 0.45, 0.60, 0.95), (160, 0.60, 1.10, 1.50)]:
        mask = (t >= s) & (t < e)
        seg = t[mask] - s
        clean[mask] = amp * np.sin(2 * np.pi * f0 * seg) * np.hanning(mask.sum())
    return (clean * 0.7).astype(np.float32)


def read_wav(payload: bytes) -> tuple[np.ndarray, int]:
    import soundfile as sf

    return sf.read(io.BytesIO(payload), dtype="float32", always_2d=False)


def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["operations"] == 2


def test_operations_lists_both(client: TestClient) -> None:
    items = client.get("/operations").json()["items"]
    assert [item["name"] for item in items] == ["add_noise", "denoise"]
    assert "snr_db" in items[0]["params_schema"]["properties"]
    assert "alpha" in items[1]["params_schema"]["properties"]


def test_add_noise_endpoint_roundtrip(client: TestClient) -> None:
    clean = speech_like()
    response = client.post(
        "/add-noise",
        files={"file": ("a.wav", wav_bytes(clean), "audio/wav")},
        data={"snr_db": 10.0, "noise_type": "white", "seed": 42},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    data, sr = read_wav(response.content)
    assert sr == SR
    assert data.shape == clean.shape
    from app.dsp import estimate_snr

    assert estimate_snr(clean, data) == pytest.approx(10.0, abs=0.5)


def test_add_noise_invalid_type_returns_422(client: TestClient) -> None:
    response = client.post(
        "/add-noise",
        files={"file": ("a.wav", wav_bytes(tone(0.2)), "audio/wav")},
        data={"snr_db": 10.0, "noise_type": "blue"},
    )
    assert response.status_code == 422


def test_add_noise_snr_out_of_range_returns_422(client: TestClient) -> None:
    response = client.post(
        "/add-noise",
        files={"file": ("a.wav", wav_bytes(tone(0.2)), "audio/wav")},
        data={"snr_db": 999.0},
    )
    assert response.status_code == 422


def test_denoise_endpoint_roundtrip(client: TestClient) -> None:
    clean = speech_like()
    from app.audio import add_noise_audio

    noisy = add_noise_audio(clean, SR, 5.0, "white", 42)
    response = client.post(
        "/denoise",
        files={"file": ("a.wav", wav_bytes(noisy), "audio/wav")},
        data={"alpha": 2.0, "beta": 0.02},
    )
    assert response.status_code == 200
    data, sr = read_wav(response.content)
    assert sr == SR and data.shape == noisy.shape
    from app.dsp import estimate_snr

    assert estimate_snr(clean, data) > estimate_snr(clean, noisy) + 1.0


def test_snr_endpoint(client: TestClient) -> None:
    clean = speech_like()
    from app.audio import add_noise_audio

    noisy = add_noise_audio(clean, SR, 10.0, "white", 42)
    response = client.post(
        "/snr",
        files={
            "clean": ("c.wav", wav_bytes(clean), "audio/wav"),
            "noisy": ("n.wav", wav_bytes(noisy), "audio/wav"),
        },
    )
    assert response.status_code == 200
    assert response.json()["snr_db"] == pytest.approx(10.0, abs=0.5)


def test_snr_channel_mismatch_returns_422(client: TestClient) -> None:
    mono = tone(0.2)
    stereo = np.stack([mono, mono * 0.5], axis=1)
    response = client.post(
        "/snr",
        files={
            "clean": ("c.wav", wav_bytes(mono), "audio/wav"),
            "noisy": ("n.wav", wav_bytes(stereo), "audio/wav"),
        },
    )
    assert response.status_code == 422


def test_garbage_upload_returns_415(client: TestClient) -> None:
    response = client.post(
        "/add-noise", files={"file": ("bad.wav", b"not-a-wav", "audio/wav")}, data={}
    )
    assert response.status_code == 415


def test_stereo_roundtrip_preserves_channels(client: TestClient) -> None:
    """立体声输入逐通道处理，声道数原样返回（dzxt 曾在此栽过 500）。"""
    mono = tone(0.5)
    stereo = np.stack([mono, mono * 0.8], axis=1)
    response = client.post(
        "/denoise",
        files={"file": ("s.wav", wav_bytes(stereo), "audio/wav")},
        data={"alpha": 2.0},
    )
    assert response.status_code == 200
    data, _ = read_wav(response.content)
    assert data.ndim == 2 and data.shape[1] == 2
