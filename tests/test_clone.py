"""克隆链路测试（3.1）。

子服务离线时的降级行为，与在线时的完整代理+入库流程。
在线路径不依赖真实适配层/引擎：向 TTSProvider 单例注入桩实现。
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient

import server.core.effects  # noqa: F401
from server.main import app
from server.schemas import (
    CloneRefMeta,
    CloneStatusResponse,
    CloneSynthesizeRequest,
)
from server.session_store import get_store
from server.tts_provider import ProviderError, TTSProvider, set_provider


@pytest.fixture()
def client():
    get_store()._items.clear()
    set_provider(None)  # 恢复真实单例（离线态测试用它）
    with TestClient(app) as test_client:
        yield test_client
    set_provider(None)


def _wav_bytes(seconds: float = 0.5, sr: int = 32000) -> bytes:
    t = np.linspace(0, seconds, int(seconds * sr), endpoint=False)
    data = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, data, sr, format="WAV")
    return buf.getvalue()


class _Ref:
    def __init__(self) -> None:
        self.deleted: list[str] = []


REF = CloneRefMeta(
    ref_id="ref001",
    filename="sample.wav",
    duration=6.0,
    sample_rate=32000,
    prompt_text="参考文本",
    sample_text="预设合成文本",
    created_at="2026-09-08T12:00:00",
)

CLONE_BYTES = b"PK\x03\x04 fake clone package bytes"


class FakeProvider(TTSProvider):
    """最小桩：refs 仓库一条 + 合成返回预置 WAV。"""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[str] = []
        self.exported: list[str] = []
        self.imported: tuple[bytes, str] | None = None
        self.last_request: CloneSynthesizeRequest | None = None

    def name(self) -> str:
        return "fake"

    def health(self) -> CloneStatusResponse:
        if self.fail:
            return CloneStatusResponse(adapter_online=False, adapter_detail="down")
        return CloneStatusResponse(
            adapter_online=True, engine_online=True, adapter_detail="ok", refs=1
        )

    def list_refs(self) -> list[CloneRefMeta]:
        if self.fail:
            raise ProviderError("down")
        return [REF]

    def upload_ref(self, data: bytes, filename: str, prompt_text: str) -> CloneRefMeta:
        if self.fail:
            raise ProviderError("down")
        return REF.model_copy(update={"filename": filename, "prompt_text": prompt_text})

    def update_ref_prompt(self, ref_id: str, prompt_text: str) -> CloneRefMeta:
        return REF.model_copy(update={"prompt_text": prompt_text})

    def delete_ref(self, ref_id: str) -> None:
        self.deleted.append(ref_id)

    def export_ref(self, ref_id: str) -> bytes:
        if self.fail:
            raise ProviderError("down")
        self.exported.append(ref_id)
        return CLONE_BYTES

    def import_ref(self, data: bytes, filename: str) -> CloneRefMeta:
        if self.fail:
            raise ProviderError("down")
        self.imported = (data, filename)
        return REF.model_copy(update={"filename": "导入音色.wav"})

    def synthesize(self, request: CloneSynthesizeRequest) -> bytes:
        if self.fail:
            raise ProviderError("引擎不可达")
        self.last_request = request
        return _wav_bytes()


# ---------- 离线降级 ----------


def test_status_reports_offline_without_raising(client: TestClient) -> None:
    """子服务全链路离线时，status 必须是 200 + offline，绝不 500。"""
    response = client.get("/api/clone/status")
    assert response.status_code == 200
    body = response.json()
    assert body["adapter_online"] is False
    assert body["engine_online"] is False


def test_synthesize_offline_returns_503_with_hint(client: TestClient) -> None:
    response = client.post("/api/clone/synthesize", json={"ref_id": "x", "text": "你好"})
    assert response.status_code == 503
    assert "克隆子服务未就绪" in response.json()["detail"]


def test_refs_offline_returns_503(client: TestClient) -> None:
    response = client.get("/api/clone/refs")
    assert response.status_code == 503


def test_synthesize_validates_text_length(client: TestClient) -> None:
    response = client.post("/api/clone/synthesize", json={"ref_id": "x", "text": ""})
    assert response.status_code == 422


# ---------- 在线完整流程（桩注入） ----------


@pytest.fixture()
def fake_provider(client: TestClient):
    provider = FakeProvider()
    set_provider(provider)
    yield provider
    set_provider(None)


def test_status_online(fake_provider: FakeProvider, client: TestClient) -> None:
    body = client.get("/api/clone/status").json()
    assert body["adapter_online"] is True
    assert body["engine_online"] is True
    assert body["refs"] == 1


def test_upload_ref_proxies_to_provider(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    response = client.post(
        "/api/clone/refs",
        files={"file": ("demo.wav", b"x", "audio/wav")},
        data={"prompt_text": "演示"},
    )
    assert response.status_code == 201
    assert response.json()["filename"] == "demo.wav"
    assert response.json()["prompt_text"] == "演示"


def test_delete_ref_proxies(fake_provider: FakeProvider, client: TestClient) -> None:
    assert client.delete("/api/clone/refs/ref001").status_code == 204
    assert fake_provider.deleted == ["ref001"]


def test_synthesize_returns_handle_and_stores_audio(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    response = client.post(
        "/api/clone/synthesize",
        json={"ref_id": "ref001", "text": "你好世界", "prompt_text": "参考文本"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["audio_id"] == body["meta"]["audio_id"]
    assert body["text"] == "你好世界"
    assert body["meta"]["label"].startswith("克隆·")

    # 产物入库且采样率来自引擎输出（桩为 32kHz）
    entry = get_store().get(body["audio_id"])
    assert entry.sample_rate == 32000
    assert entry.duration == pytest.approx(0.5, rel=0.05)

    # 请求参数完整转发到 Provider
    assert fake_provider.last_request is not None
    assert fake_provider.last_request.prompt_text == "参考文本"


def test_synthesize_engine_failure_maps_to_503(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    fake_provider.fail = True
    response = client.post("/api/clone/synthesize", json={"ref_id": "ref001", "text": "你好"})
    assert response.status_code == 503


def test_export_ref_proxies(fake_provider: FakeProvider, client: TestClient) -> None:
    response = client.get("/api/clone/refs/ref001/export")
    assert response.status_code == 200
    assert response.content == CLONE_BYTES
    assert "attachment" in response.headers["content-disposition"]
    assert ".clone" in response.headers["content-disposition"]
    assert fake_provider.exported == ["ref001"]


def test_export_ref_offline_returns_503(client: TestClient) -> None:
    response = client.get("/api/clone/refs/ref001/export")
    assert response.status_code == 503


def test_import_ref_proxies(fake_provider: FakeProvider, client: TestClient) -> None:
    response = client.post(
        "/api/clone/refs/import",
        files={"file": ("voice.clone", CLONE_BYTES, "application/octet-stream")},
    )
    assert response.status_code == 200
    assert response.json()["filename"] == "导入音色.wav"
    assert fake_provider.imported == (CLONE_BYTES, "voice.clone")


def test_import_ref_offline_returns_503(client: TestClient) -> None:
    response = client.post(
        "/api/clone/refs/import",
        files={"file": ("voice.clone", CLONE_BYTES, "application/octet-stream")},
    )
    assert response.status_code == 503


# ---------- 合成参数透传（更多可调参数） ----------


def test_synthesize_passes_all_engine_params(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    response = client.post(
        "/api/clone/synthesize",
        json={
            "ref_id": "ref001",
            "text": "你好",
            "prompt_text": "参考",
            "text_lang": "en",
            "prompt_lang": "en",
            "speed_factor": 1.2,
            "text_split_method": "cut3",
            "batch_size": 4,
            "fragment_interval": 0.5,
            "temperature": 0.8,
            "top_k": 30,
            "top_p": 0.9,
            "repetition_penalty": 1.5,
            "seed": 42,
        },
    )
    assert response.status_code == 200
    request = fake_provider.last_request
    assert request is not None
    assert request.text_lang == "en"
    assert request.speed_factor == 1.2
    assert request.text_split_method == "cut3"
    assert request.batch_size == 4
    assert request.fragment_interval == 0.5
    assert request.temperature == 0.8
    assert request.top_k == 30
    assert request.top_p == 0.9
    assert request.repetition_penalty == 1.5
    assert request.seed == 42


def test_synthesize_defaults_backward_compatible(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    response = client.post(
        "/api/clone/synthesize", json={"ref_id": "ref001", "text": "你好"}
    )
    assert response.status_code == 200
    request = fake_provider.last_request
    assert request is not None
    assert request.text_lang == "zh"
    assert request.speed_factor == 1.0
    assert request.text_split_method == "cut5"
    assert request.batch_size == 1
    assert request.seed == -1
