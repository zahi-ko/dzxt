"""NoiseProvider 抽象层：主干与加噪降噪子服务之间唯一的耦合点。

架构（ADR 0008）：

    主干 ──HTTP──▶ noise-service(9910)     无状态、不落盘、不含模型

- LocalAdapterProvider：经 HTTP 调用本地 noise-service（当前唯一实现）
- 独立子服务位于 dzxt 仓库之外（C:\\Users\\zahi\\Desktop\\noise-service），
  独立 git / 独立 venv，本文件与 server/api/routers/noise.py 是主干侧全部耦合。
- 所有网络异常统一收敛为 ProviderError，路由层据此返回 503，
  保证子服务离线时只影响加噪/降噪，不拖垮基础功能演示。

httpx 的 trust_env=False 是 2026-09-08 克隆链路实测教训：系统代理会劫持
回环调用，本文件沿用同一设置。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

import httpx

from server.schemas import (
    NoiseOperationInfo,
    NoiseStatusResponse,
)

ADAPTER_TIMEOUT = httpx.Timeout(10.0, read=120.0)

# operation → 子服务端点。新增操作只需两边同步这一张表。
_OPERATION_ENDPOINTS = {
    "add_noise": "/add-noise",
    "denoise": "/denoise",
}


class ProviderError(RuntimeError):
    """子服务调用失败。status_code 用于路由层映射 HTTP 状态。"""

    def __init__(self, detail: str, status_code: int = 503) -> None:
        super().__init__(detail)
        self.status_code = status_code


class NoiseProvider(ABC):
    """加噪降噪子服务抽象。实现方负责把网络异常翻译成 ProviderError。"""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def health(self) -> NoiseStatusResponse: ...

    @abstractmethod
    def list_operations(self) -> list[NoiseOperationInfo]: ...

    @abstractmethod
    def process(self, operation: str, wav_bytes: bytes, params: dict) -> bytes:
        """施加操作并返回 WAV 字节。失败抛 ProviderError。"""

    @abstractmethod
    def estimate_snr(self, clean_bytes: bytes, noisy_bytes: bytes) -> float:
        """计算实际信噪比（dB）。失败抛 ProviderError。"""


class LocalAdapterProvider(NoiseProvider):
    """经 HTTP 调用本地 noise-service。"""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (
            base_url or os.environ.get("NOISE_SERVICE_URL", "http://127.0.0.1:9910")
        ).rstrip("/")
        self._client = httpx.Client(timeout=ADAPTER_TIMEOUT, trust_env=False)

    def name(self) -> str:
        return f"local-adapter({self.base_url})"

    def health(self) -> NoiseStatusResponse:
        try:
            response = self._client.get(f"{self.base_url}/health")
            response.raise_for_status()
        except Exception as exc:
            return NoiseStatusResponse(
                online=False,
                detail=f"子服务 {self.base_url} 不可达：{exc.__class__.__name__}",
            )
        return NoiseStatusResponse(online=True, detail="ok")

    def list_operations(self) -> list[NoiseOperationInfo]:
        body = self._request("GET", "/operations")
        return [NoiseOperationInfo(**item) for item in body.get("items", [])]

    def process(self, operation: str, wav_bytes: bytes, params: dict) -> bytes:
        endpoint = _OPERATION_ENDPOINTS.get(operation)
        if endpoint is None:
            raise ProviderError(
                f"未知操作: {operation}。已支持: {', '.join(sorted(_OPERATION_ENDPOINTS))}",
                status_code=404,
            )
        response = self._request(
            "POST",
            endpoint,
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            # None = 用子服务默认值，直接不进表单（空串会让 int 字段解析失败）
            data={key: value for key, value in (params or {}).items() if value is not None},
        )
        content = response if isinstance(response, bytes) else b""
        if len(content) < 44:  # WAV 头至少 44 字节
            raise ProviderError("子服务返回了空音频", status_code=502)
        return content

    def estimate_snr(self, clean_bytes: bytes, noisy_bytes: bytes) -> float:
        body = self._request(
            "POST",
            "/snr",
            files={
                "clean": ("clean.wav", clean_bytes, "audio/wav"),
                "noisy": ("noisy.wav", noisy_bytes, "audio/wav"),
            },
        )
        return float(body.get("snr_db", float("nan")))

    def _request(self, method: str, path: str, **kwargs):
        """统一请求入口。音频端点（multipart）返回 bytes，JSON 端点返回 dict。"""
        try:
            response = self._client.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"子服务连接失败：{exc.__class__.__name__}") from exc

        if response.status_code >= 400:
            raise ProviderError(_detail_of(response), status_code=response.status_code)

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return response.content


def _detail_of(response: httpx.Response) -> str:
    try:
        body = response.json()
        detail = body.get("detail", body)
        return str(detail)
    except Exception:
        return response.text[:200] or f"HTTP {response.status_code}"


_PROVIDER: NoiseProvider | None = None


def get_provider() -> NoiseProvider:
    """全局单例。切换实现（如云端）时替换此工厂即可，路由层零改动。"""
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = LocalAdapterProvider()
    return _PROVIDER


def set_provider(provider: NoiseProvider | None) -> None:
    """测试注入点。传 None 恢复默认单例。"""
    global _PROVIDER
    _PROVIDER = provider
