"""TTSProvider 抽象层：主干与克隆子服务之间唯一的耦合点。

架构（ADR 0004 + 2026-09-08 实施修订）：

    主干 ──HTTP──▶ services/clone 适配层(9900) ──HTTP──▶ GPT-SoVITS 引擎(9880)

- LocalAdapterProvider：经适配层调用本地 GPT-SoVITS（当前实现）
- 云端插槽：按 ADR 0004 降级预案，仅保留接口形态，不做实现——
  结题前若本地方案不可用，新增一个云端 Provider 子类即可整体切换，
  路由与前端零改动。

所有网络异常统一收敛为 ProviderError，路由层据此返回 503，
保证引擎离线时只影响克隆功能，不拖垮基础功能演示。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

import httpx

from server.schemas import (
    CloneRefMeta,
    CloneStatusResponse,
    CloneSynthesizeRequest,
)

ADAPTER_TIMEOUT = httpx.Timeout(10.0, read=300.0)


class ProviderError(RuntimeError):
    """子服务调用失败。status_code 用于路由层映射 HTTP 状态。"""

    def __init__(self, detail: str, status_code: int = 503) -> None:
        super().__init__(detail)
        self.status_code = status_code


class TTSProvider(ABC):
    """克隆子服务抽象。实现方负责把网络异常翻译成 ProviderError。"""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def health(self) -> CloneStatusResponse: ...

    @abstractmethod
    def list_refs(self) -> list[CloneRefMeta]: ...

    @abstractmethod
    def upload_ref(self, data: bytes, filename: str, prompt_text: str) -> CloneRefMeta: ...

    @abstractmethod
    def update_ref_prompt(self, ref_id: str, prompt_text: str) -> CloneRefMeta: ...

    @abstractmethod
    def delete_ref(self, ref_id: str) -> None: ...

    @abstractmethod
    def synthesize(self, request: CloneSynthesizeRequest) -> bytes:
        """合成并返回 WAV 字节。失败抛 ProviderError。"""


class LocalAdapterProvider(TTSProvider):
    """经 services/clone 适配层调用本地 GPT-SoVITS 引擎。"""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (
            base_url or os.environ.get("CLONE_SERVICE_URL", "http://127.0.0.1:9900")
        ).rstrip("/")
        self._client = httpx.Client(timeout=ADAPTER_TIMEOUT, trust_env=False)

    def name(self) -> str:
        return f"local-adapter({self.base_url})"

    def health(self) -> CloneStatusResponse:
        try:
            response = self._client.get(f"{self.base_url}/health")
            response.raise_for_status()
        except Exception as exc:
            return CloneStatusResponse(
                adapter_online=False,
                adapter_detail=f"适配层 {self.base_url} 不可达：{exc.__class__.__name__}",
            )
        body = response.json()
        return CloneStatusResponse(
            adapter_online=True,
            engine_online=body.get("engine_online", False),
            adapter_detail="ok",
            engine_detail=body.get("engine_detail", ""),
            refs=body.get("refs", 0),
        )

    def list_refs(self) -> list[CloneRefMeta]:
        body = self._request("GET", "/refs")
        return [CloneRefMeta(**item) for item in body.get("items", [])]

    def upload_ref(self, data: bytes, filename: str, prompt_text: str) -> CloneRefMeta:
        response = self._request(
            "POST",
            "/refs",
            files={"file": (filename, data, "application/octet-stream")},
            data={"prompt_text": prompt_text},
        )
        return CloneRefMeta(**response)

    def update_ref_prompt(self, ref_id: str, prompt_text: str) -> CloneRefMeta:
        return CloneRefMeta(
            **self._request("PATCH", f"/refs/{ref_id}", json={"prompt_text": prompt_text})
        )

    def delete_ref(self, ref_id: str) -> None:
        self._request("DELETE", f"/refs/{ref_id}")

    def synthesize(self, request: CloneSynthesizeRequest) -> bytes:
        payload = {
            "ref_id": request.ref_id,
            "text": request.text,
            "prompt_text": request.prompt_text,
            "text_lang": request.text_lang,
            "prompt_lang": request.prompt_lang,
            "speed_factor": request.speed_factor,
        }
        try:
            response = self._client.post(f"{self.base_url}/synthesize", json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(f"适配层连接失败：{exc.__class__.__name__}") from exc

        if response.status_code != 200:
            raise ProviderError(_detail_of(response), status_code=response.status_code)

        content = response.content
        if len(content) < 44:
            raise ProviderError("适配层返回了空音频", status_code=502)
        return content

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._client.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"适配层连接失败：{exc.__class__.__name__}") from exc

        if response.status_code >= 400:
            raise ProviderError(_detail_of(response), status_code=response.status_code)
        if response.status_code == 204:
            return {}
        return response.json()


def _detail_of(response: httpx.Response) -> str:
    try:
        body = response.json()
        detail = body.get("detail", body)
        return str(detail)
    except Exception:
        return response.text[:200] or f"HTTP {response.status_code}"


_PROVIDER: TTSProvider | None = None


def get_provider() -> TTSProvider:
    """全局单例。切换实现（如云端）时替换此工厂即可，路由层零改动。"""
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = LocalAdapterProvider()
    return _PROVIDER


def set_provider(provider: TTSProvider | None) -> None:
    """测试注入点。传 None 恢复默认单例。"""
    global _PROVIDER
    _PROVIDER = provider
