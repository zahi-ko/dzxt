"""API 冒烟测试。

覆盖「上传 → 施加效果 → 取波形 → 下载」这条主链路，
确保句柄制与注册表在 HTTP 层正确串起来。
"""

from __future__ import annotations

from pathlib import Path

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


# ---------- 阶段二新增：设备 / 效果链 / 历史 / 撤销 / 语谱图 / 流 ----------


def test_devices_endpoint(client: TestClient) -> None:
    body = client.get("/api/audio/devices").json()
    assert "items" in body
    # 无声卡的机器也应返回空列表而不是 500
    for device in body["items"]:
        assert device["channels"] >= 1


def test_record_start_rejects_unsupported_sample_rate(client: TestClient) -> None:
    response = client.post(
        "/api/audio/record/start", json={"sample_rate": 12345, "duration": None}
    )
    assert response.status_code == 400


def test_chain_applies_steps_in_order(client: TestClient) -> None:
    audio_id = upload(client)
    response = client.post(
        "/api/effects/chain",
        json={
            "audio_id": audio_id,
            "steps": [
                {"effect": "gain", "params": {"db": 6}},
                {"effect": "reverse", "params": {}},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] == ["音量增益", "倒放"]
    assert body["audio_id"] != audio_id
    # 效果链只产出一个新句柄，不留下中间产物
    assert len(client.get("/api/audio").json()["items"]) == 2


def test_chain_rejects_empty_steps(client: TestClient) -> None:
    audio_id = upload(client)
    assert client.post("/api/effects/chain", json={"audio_id": audio_id, "steps": []}).status_code == 400


def test_chain_reports_bad_step_index(client: TestClient) -> None:
    audio_id = upload(client)
    response = client.post(
        "/api/effects/chain",
        json={
            "audio_id": audio_id,
            "steps": [{"effect": "gain", "params": {}}, {"effect": "nope", "params": {}}],
        },
    )
    assert response.status_code == 404
    assert "第 2 步" in response.json()["detail"]


def test_history_records_full_lineage(client: TestClient) -> None:
    audio_id = upload(client)
    first = client.post(
        "/api/effects/apply", json={"audio_id": audio_id, "effect": "gain", "params": {"db": 3}}
    ).json()["audio_id"]
    second = client.post(
        "/api/effects/apply", json={"audio_id": first, "effect": "reverse", "params": {}}
    ).json()["audio_id"]

    body = client.get(f"/api/effects/{second}/history").json()
    assert body["root_id"] == audio_id
    assert [step["effect"] for step in body["steps"]] == ["gain", "reverse"]


def test_undo_jumps_to_previous_handle(client: TestClient) -> None:
    audio_id = upload(client)
    processed = client.post(
        "/api/effects/apply", json={"audio_id": audio_id, "effect": "gain", "params": {"db": 3}}
    ).json()["audio_id"]

    body = client.post("/api/effects/undo", json={"audio_id": processed}).json()
    assert body["audio_id"] == audio_id


def test_undo_on_original_returns_400(client: TestClient) -> None:
    audio_id = upload(client)
    assert client.post("/api/effects/undo", json={"audio_id": audio_id}).status_code == 400


def test_undo_with_deleted_parent_returns_409(client: TestClient) -> None:
    audio_id = upload(client)
    processed = client.post(
        "/api/effects/apply", json={"audio_id": audio_id, "effect": "gain", "params": {"db": 3}}
    ).json()["audio_id"]

    assert client.delete(f"/api/audio/{audio_id}").status_code == 204
    assert client.post("/api/effects/undo", json={"audio_id": processed}).status_code == 409


def test_spectrogram_endpoint(client: TestClient) -> None:
    audio_id = upload(client, seconds=1.0)
    body = client.post(
        "/api/analysis/spectrogram", json={"audio_id": audio_id, "n_fft": 512, "max_frames": 120}
    ).json()
    assert body["frames"] <= 120
    assert body["bins"] == 257
    assert len(body["data"]) == body["frames"] * body["bins"]
    assert all(0 <= value <= 255 for value in body["data"][:1000])


def test_stream_is_inline_wav(client: TestClient) -> None:
    audio_id = upload(client)
    response = client.get(f"/api/audio/{audio_id}/stream")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert "inline" in response.headers["content-disposition"]
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content[:4] == b"RIFF"


def test_stream_supports_range_requests(client: TestClient) -> None:
    """浏览器 media 元素依赖 206 响应做 seek；缺失时拖动进度条/单击定位失效。"""
    audio_id = upload(client)
    full = client.get(f"/api/audio/{audio_id}/stream").content
    total = len(full)

    # bytes=start-end
    response = client.get(f"/api/audio/{audio_id}/stream", headers={"Range": "bytes=100-199"})
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 100-199/{total}"
    assert response.content == full[100:200]

    # bytes=start-（开放式结尾）
    response = client.get(f"/api/audio/{audio_id}/stream", headers={"Range": "bytes=0-"})
    assert response.status_code == 206
    assert response.content == full

    # bytes=-N（后缀范围）
    response = client.get(f"/api/audio/{audio_id}/stream", headers={"Range": "bytes=-4410"})
    assert response.status_code == 206
    assert response.content == full[-4410:]

    # 起点越界
    response = client.get(f"/api/audio/{audio_id}/stream", headers={"Range": f"bytes={total}-"})
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{total}"


def test_upload_mp3(client: TestClient) -> None:
    """mp3 上传解码。测试音频不入库（.gitignore），缺失时跳过。"""
    mp3_path = Path(__file__).parent / "test_short.mp3"
    if not mp3_path.exists():
        pytest.skip("测试音频 test_short.mp3 不存在")
    response = client.post(
        "/api/audio/upload",
        files={"file": ("test_short.mp3", mp3_path.read_bytes(), "audio/mpeg")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sample_rate"] == 44100
    assert body["channels"] == 2
    assert body["duration"] == pytest.approx(30.0, abs=0.5)


def test_load_audio_tolerates_mp3_tail_overclaim(client: TestClient) -> None:
    """VBR mp3 头部声明的帧数常大于实际可解码帧数，尾部读取会抛错误码 29。

    回归测试：解码应保留成功部分而不是整体失败。test.mp3（11 分钟原片）
    正是这种文件；缺失时跳过。
    """
    mp3_path = Path(__file__).parent / "test.mp3"
    if not mp3_path.exists():
        pytest.skip("测试音频 test.mp3 不存在")
    from server.core.io.audio_file import load_audio

    data, sample_rate = load_audio(mp3_path.read_bytes())
    assert sample_rate == 44100
    # 实际可解码约 270.5s；声明 271.8s，尾部约 1s 坏帧被截断
    assert data.shape[0] > 44100 * 260


def test_recording_labels_are_numbered(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """多次录音按会话内序号命名（录音 1、录音 2…），不用时间戳。"""

    class FakeRecorder:
        def stop(self) -> tuple[np.ndarray, int]:
            return np.zeros(8000, dtype=np.float32), 16000

    monkeypatch.setattr("server.api.routers.audio.get_recorder", lambda: FakeRecorder())

    labels = [client.post("/api/audio/record/stop").json()["label"] for _ in range(3)]
    assert labels == ["录音 1", "录音 2", "录音 3"]
