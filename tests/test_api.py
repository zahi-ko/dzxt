"""API 冒烟测试。

覆盖「上传 → 施加效果 → 取波形 → 下载」这条主链路，
确保句柄制与注册表在 HTTP 层正确串起来。
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

import server.core.effects  # noqa: F401
from server.core.io.audio_file import dump_audio
from server.main import app
from server.session_store import get_store


@pytest.fixture()
def client():
    get_store()._items.clear()  # 句柄仓库是全局单例，测试间必须隔离
    with TestClient(app) as test_client:
        yield test_client


def wav_bytes(seconds: float = 0.5, sr: int = 16000) -> bytes:
    t = np.linspace(0, seconds, int(seconds * sr), endpoint=False)
    data = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    return dump_audio(data, sr)


def upload(client: TestClient, seconds: float = 0.5) -> str:
    response = client.post(
        "/api/audio/upload", files={"file": ("t.wav", wav_bytes(seconds), "audio/wav")}
    )
    assert response.status_code == 200
    return response.json()["audio_id"]


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["effects"] > 0


def test_list_effects(client: TestClient) -> None:
    items = client.get("/api/effects").json()["items"]
    assert any(item["name"] == "reverse" for item in items)


def test_upload_then_list(client: TestClient) -> None:
    audio_id = upload(client)
    listed = client.get("/api/audio").json()["items"]
    assert len(listed) == 1
    assert listed[0]["audio_id"] == audio_id
    assert listed[0]["duration"] == pytest.approx(0.5, rel=0.05)


def test_apply_effect_creates_new_handle(client: TestClient) -> None:
    audio_id = upload(client)

    response = client.post(
        "/api/effects/apply",
        json={"audio_id": audio_id, "effect": "reverse", "params": {}, "save_as_new": True},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["audio_id"] != audio_id
    assert len(client.get("/api/audio").json()["items"]) == 2


def test_apply_effect_overwrite_keeps_handle(client: TestClient) -> None:
    audio_id = upload(client)

    response = client.post(
        "/api/effects/apply",
        json={"audio_id": audio_id, "effect": "gain", "params": {"db": -6}, "save_as_new": False},
    )
    assert response.status_code == 200
    assert response.json()["audio_id"] == audio_id
    assert len(client.get("/api/audio").json()["items"]) == 1


def test_apply_unknown_effect_returns_404(client: TestClient) -> None:
    audio_id = upload(client)
    response = client.post(
        "/api/effects/apply", json={"audio_id": audio_id, "effect": "nope", "params": {}}
    )
    assert response.status_code == 404


def test_apply_with_invalid_params_returns_422(client: TestClient) -> None:
    audio_id = upload(client)
    response = client.post(
        "/api/effects/apply",
        json={"audio_id": audio_id, "effect": "gain", "params": {"db": 999}},
    )
    assert response.status_code == 422


def test_peaks_returns_envelope(client: TestClient) -> None:
    audio_id = upload(client, seconds=1.0)
    body = client.get(f"/api/audio/{audio_id}/peaks?points=500").json()
    assert body["points"] == 500
    assert len(body["minimum"]) == 500
    assert len(body["maximum"]) == 500


def test_spectrum(client: TestClient) -> None:
    audio_id = upload(client, seconds=1.0)
    body = client.post("/api/analysis/spectrum", json={"audio_id": audio_id, "n_fft": 1024}).json()
    assert len(body["freqs"]) == 513
    assert len(body["magnitude_db"]) == 513


def test_stats(client: TestClient) -> None:
    audio_id = upload(client)
    body = client.get(f"/api/analysis/{audio_id}/stats").json()
    assert body["audio_id"] == audio_id
    assert body["sample_rate"] == 16000
    assert body["channels"] == 1
    assert body["duration"] == pytest.approx(0.5, rel=0.05)
    assert 0 < body["peak"] <= 1
    assert 0 < body["rms"] <= body["peak"]


def test_download_returns_wav(client: TestClient) -> None:
    audio_id = upload(client)
    response = client.get(f"/api/audio/{audio_id}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"


def test_missing_handle_returns_404(client: TestClient) -> None:
    assert client.get("/api/audio/does-not-exist/peaks").status_code == 404
    assert client.get("/api/audio/does-not-exist/download").status_code == 404
    assert client.delete("/api/audio/does-not-exist").status_code == 404


def test_delete_handle(client: TestClient) -> None:
    audio_id = upload(client)
    assert client.delete(f"/api/audio/{audio_id}").status_code == 204
    assert client.get("/api/audio").json()["items"] == []


def test_upload_rejects_garbage(client: TestClient) -> None:
    response = client.post(
        "/api/audio/upload", files={"file": ("bad.wav", b"not-a-wav", "audio/wav")}
    )
    assert response.status_code == 415
