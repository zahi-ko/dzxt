"""加噪降噪链路测试（3.3）。

子服务离线时的降级行为，与在线时的完整处理+入库流程。
在线路径不依赖真实子服务：向 NoiseProvider 单例注入桩实现。
"""

from __future__ import annotations

import io

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import server.core.effects  # noqa: F401
from server.main import app
from server.noise_provider import (
    LocalAdapterProvider,
    NoiseProvider,
    ProviderError,
    get_provider,
    set_provider,
)
from server.schemas import NoiseOperationInfo, NoiseStatusResponse
from server.session_store import get_store

OPERATIONS = [
    NoiseOperationInfo(name="add_noise", title="加噪", description="加噪", params_schema={}),
    NoiseOperationInfo(name="denoise", title="谱减降噪", description="降噪", params_schema={}),
]


@pytest.fixture()
def client():
    get_store()._items.clear()
    # 离线降级测试不能依赖「9910 恰好没人监听」——本机子服务可能正在运行。
    # 注入指向确定不可达地址的真 Provider，离线路径才可复现。
    set_provider(LocalAdapterProvider(base_url="http://127.0.0.1:1"))
    with TestClient(app) as test_client:
        yield test_client
    set_provider(None)


@pytest.fixture()
def online_client():
    get_store()._items.clear()
    set_provider(FakeProvider())
    with TestClient(app) as test_client:
        yield test_client
    set_provider(None)


def _wav_bytes(seconds: float = 0.5, sr: int = 16000) -> bytes:
    t = np.linspace(0, seconds, int(seconds * sr), endpoint=False)
    data = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    buffer = io.BytesIO()
    sf.write(buffer, data, sr, format="WAV")
    return buffer.getvalue()


def upload(client: TestClient) -> str:
    response = client.post(
        "/api/audio/upload", files={"file": ("t.wav", _wav_bytes(), "audio/wav")}
    )
    assert response.status_code == 200
    return response.json()["audio_id"]


class FakeProvider(NoiseProvider):
    """最小桩：两个操作 + process 返回预置 WAV + 固定 SNR。"""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.last_call: tuple[str, bytes, dict] | None = None
        self.snr_calls: list[tuple[bytes, bytes]] = []

    def name(self) -> str:
        return "fake"

    def health(self) -> NoiseStatusResponse:
        return NoiseStatusResponse(online=True, detail="fake")

    def list_operations(self) -> list[NoiseOperationInfo]:
        return list(OPERATIONS)

    def process(self, operation: str, wav_bytes: bytes, params: dict) -> bytes:
        if operation not in {"add_noise", "denoise"}:
            raise ProviderError(f"未知操作: {operation}", status_code=404)
        if self.fail:
            raise ProviderError("子服务炸了")
        self.last_call = (operation, wav_bytes, params)
        return _wav_bytes()

    def estimate_snr(self, clean_bytes: bytes, noisy_bytes: bytes) -> float:
        self.snr_calls.append((clean_bytes, noisy_bytes))
        return 12.5


# ---------- 离线降级 ----------


def test_status_offline_returns_200_online_false(client: TestClient) -> None:
    body = client.get("/api/noise/status").json()
    assert body["online"] is False
    assert "不可达" in body["detail"]


def test_process_offline_returns_503(client: TestClient) -> None:
    audio_id = upload(client)
    response = client.post(
        "/api/noise/process",
        json={"audio_id": audio_id, "operation": "add_noise", "params": {"snr_db": 10}},
    )
    assert response.status_code == 503
    assert "子服务未就绪" in response.json()["detail"]


def test_operations_offline_returns_503(client: TestClient) -> None:
    assert client.get("/api/noise/operations").status_code == 503


# ---------- 在线路径 ----------


def test_status_online(online_client: TestClient) -> None:
    body = online_client.get("/api/noise/status").json()
    assert body["online"] is True


def test_operations_proxy(online_client: TestClient) -> None:
    items = online_client.get("/api/noise/operations").json()["items"]
    assert [item["name"] for item in items] == ["add_noise", "denoise"]


def test_process_creates_handle_with_lineage(online_client: TestClient) -> None:
    audio_id = upload(online_client)
    response = online_client.post(
        "/api/noise/process",
        json={
            "audio_id": audio_id,
            "operation": "add_noise",
            "params": {"snr_db": 10.0, "noise_type": "white", "seed": 42},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["operation"] == "add_noise"
    assert body["audio_id"] != audio_id
    assert len(online_client.get("/api/audio").json()["items"]) == 2

    # 参数原样透传给子服务
    provider = get_provider()
    assert isinstance(provider, FakeProvider)
    operation, payload, params = provider.last_call
    assert operation == "add_noise"
    assert params == {"snr_db": 10.0, "noise_type": "white", "seed": 42}
    assert payload[:4] == b"RIFF"  # 发给子服务的是 WAV 字节

    # 血统：history 可见 noise 步骤，undo 可回到原始句柄
    history = online_client.get(f"/api/effects/{body['audio_id']}/history").json()
    assert [step["effect"] for step in history["steps"]] == ["noise.add_noise"]
    assert history["root_id"] == audio_id
    undo = online_client.post("/api/effects/undo", json={"audio_id": body["audio_id"]}).json()
    assert undo["audio_id"] == audio_id


def test_process_denoise_operation(online_client: TestClient) -> None:
    audio_id = upload(online_client)
    response = online_client.post(
        "/api/noise/process",
        json={"audio_id": audio_id, "operation": "denoise", "params": {"alpha": 2.0}},
    )
    assert response.status_code == 200
    assert get_provider().last_call[0] == "denoise"


def test_process_unknown_operation_returns_404(online_client: TestClient) -> None:
    audio_id = upload(online_client)
    response = online_client.post(
        "/api/noise/process",
        json={"audio_id": audio_id, "operation": "nope", "params": {}},
    )
    assert response.status_code == 404


def test_process_provider_error_returns_503(online_client: TestClient) -> None:
    set_provider(FakeProvider(fail=True))
    audio_id = upload(online_client)
    response = online_client.post(
        "/api/noise/process",
        json={"audio_id": audio_id, "operation": "denoise", "params": {}},
    )
    assert response.status_code == 503
    assert "子服务未就绪" in response.json()["detail"]


def test_process_missing_handle_returns_404(online_client: TestClient) -> None:
    response = online_client.post(
        "/api/noise/process",
        json={"audio_id": "does-not-exist", "operation": "denoise", "params": {}},
    )
    assert response.status_code == 404


def test_process_empty_audio_returns_400(online_client: TestClient) -> None:
    entry = get_store().put(np.zeros(0, dtype=np.float32), 16000)
    response = online_client.post(
        "/api/noise/process",
        json={"audio_id": entry.audio_id, "operation": "denoise", "params": {}},
    )
    assert response.status_code == 400


# ---------- 闭环验证：SNR ----------


def test_snr_endpoint(online_client: TestClient) -> None:
    audio_id = upload(online_client)
    body = online_client.post(
        "/api/noise/snr", json={"clean_id": audio_id, "noisy_id": audio_id}
    ).json()
    assert body["snr_db"] == 12.5
    # 两个句柄的 WAV 字节都发给了子服务
    assert len(get_provider().snr_calls) == 1
    clean, noisy = get_provider().snr_calls[0]
    assert clean[:4] == b"RIFF" and noisy[:4] == b"RIFF"


def test_snr_missing_handle_returns_404(online_client: TestClient) -> None:
    response = online_client.post(
        "/api/noise/snr", json={"clean_id": "nope", "noisy_id": "nope"}
    )
    assert response.status_code == 404
