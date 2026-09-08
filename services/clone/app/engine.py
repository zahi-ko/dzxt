"""GPT-SoVITS 引擎 HTTP 客户端。

引擎侧仅依赖官方 api_v2.py 暴露的端点：
- GET  /openapi.json   探活（FastAPI 自带，无副作用）
- POST /tts            合成，返回音频字节（media_type=wav）

探活特意不用 /control（restart/exit 有副作用），也不假设 /docs 可用。
"""

from __future__ import annotations

import httpx

from app.config import ENGINE_BASE_URL, HEALTH_TIMEOUT, SYNTH_TIMEOUT


class EngineError(RuntimeError):
    """引擎调用失败（对映 HTTP 502/503）。"""


class EngineClient:
    """无状态客户端，可整体替换（测试注入 MockTransport）。"""

    def __init__(self, base_url: str = ENGINE_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def health(self) -> dict:
        """探测引擎是否在线。返回 {"online": bool, "detail": str}，绝不抛异常。"""
        try:
            response = httpx.get(
                f"{self.base_url}/openapi.json", timeout=HEALTH_TIMEOUT, trust_env=False
            )
            response.raise_for_status()
            title = response.json().get("info", {}).get("title", "")
            return {"online": True, "detail": title}
        except Exception as exc:
            return {
                "online": False,
                "detail": f"引擎 {self.base_url} 不可达：{exc.__class__.__name__}",
            }

    def synthesize(self, payload: dict) -> bytes:
        """提交合成请求，返回 WAV 字节。失败抛 EngineError。"""
        body = {
            "media_type": "wav",
            "text_split_method": "cut5",
            **payload,
        }
        try:
            response = httpx.post(
                f"{self.base_url}/tts", json=body, timeout=SYNTH_TIMEOUT, trust_env=False
            )
        except httpx.TimeoutException as exc:
            raise EngineError("引擎合成超时：文本是否过长？可尝试缩短后重试") from exc
        except httpx.HTTPError as exc:
            raise EngineError(f"引擎连接失败：{exc.__class__.__name__}") from exc

        if response.status_code != 200:
            detail = _extract_detail(response)
            raise EngineError(f"引擎返回 {response.status_code}：{detail}")

        content = response.content
        if len(content) < 44:  # 连最小 WAV 头都不到，视为空结果
            raise EngineError("引擎返回了空音频")
        return content


def _extract_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        detail = body.get("message") or body.get("detail") or body
        return str(detail)
    except Exception:
        return response.text[:200] or "(无响应体)"
