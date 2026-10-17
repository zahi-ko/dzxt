"""语音加噪与降噪路由（3.3）。

主干不接触子服务的任何实现细节，全部经由 NoiseProvider；
处理产物直接写入 SessionStore——因此「加噪/降噪结果回流音频列表、
可继续施加效果、可 A/B 对比」无需任何额外代码。
产物带血统（source_id + steps），撤销与处理历史天然成立。
"""

from __future__ import annotations

import io

import soundfile as sf
from fastapi import APIRouter, HTTPException

from server.api.deps import require_entry
from server.core.io.audio_file import dump_audio
from server.noise_provider import ProviderError, get_provider
from server.schemas import (
    EffectHistoryItem,
    NoiseOperationListResponse,
    NoiseProcessRequest,
    NoiseProcessResponse,
    NoiseSnrRequest,
    NoiseSnrResponse,
    NoiseStatusResponse,
)
from server.session_store import get_store

router = APIRouter(prefix="/api/noise", tags=["noise"])

# 子服务离线时的统一提示。真实原因在 status/detail 里可查。
_OFFLINE_HINT = "加噪降噪子服务未就绪，请先启动 noise-service（见 AGENT.md §3.5）"

_OPERATION_TITLES = {"add_noise": "加噪", "denoise": "谱减降噪"}


def _provider_error(exc: ProviderError) -> HTTPException:
    status = exc.status_code if exc.status_code in (400, 404, 415, 422, 502) else 503
    detail = str(exc)
    if status == 503:
        detail = f"{_OFFLINE_HINT}（{detail}）"
    return HTTPException(status_code=status, detail=detail)


@router.get("/status", response_model=NoiseStatusResponse, summary="子服务状态")
def status() -> NoiseStatusResponse:
    """探活失败永远返回 200 + online=false，让前端从容展示离线态。"""
    try:
        return get_provider().health()
    except Exception:  # ProviderError 及一切意外都不应影响前端渲染
        return NoiseStatusResponse(online=False, detail="探活异常")


@router.get("/operations", response_model=NoiseOperationListResponse, summary="列出操作与参数结构")
def list_operations() -> NoiseOperationListResponse:
    try:
        return NoiseOperationListResponse(items=get_provider().list_operations())
    except ProviderError as exc:
        raise _provider_error(exc) from exc


@router.post("/process", response_model=NoiseProcessResponse, summary="加噪/降噪并入库")
def process(request: NoiseProcessRequest) -> NoiseProcessResponse:
    """对句柄音频施加加噪/降噪，产物按句柄制入库（含血统，可撤销）。"""
    provider = get_provider()
    entry = require_entry(request.audio_id)
    if entry.data.size == 0:
        raise HTTPException(status_code=400, detail="音频内容为空，无法处理")

    try:
        wav = provider.process(
            request.operation,
            dump_audio(entry.data, entry.sample_rate),
            request.params,
        )
    except ProviderError as exc:
        raise _provider_error(exc) from exc

    try:
        data, sr = sf.read(io.BytesIO(wav), dtype="float32", always_2d=False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"处理音频解码失败：{exc}") from exc

    title = _OPERATION_TITLES.get(request.operation, request.operation)
    label = f"{entry.label or entry.audio_id} → {title}"
    steps = entry.steps + [
        EffectHistoryItem(
            effect=f"noise.{request.operation}",
            title=title,
            params=request.params,
        )
    ]
    target = get_store().put(
        data, sr, label=label, source_id=entry.audio_id, steps=steps
    )
    meta = target.to_meta()
    return NoiseProcessResponse(audio_id=meta.audio_id, meta=meta, operation=request.operation)


@router.post("/snr", response_model=NoiseSnrResponse, summary="计算实际信噪比（闭环验证）")
def snr(request: NoiseSnrRequest) -> NoiseSnrResponse:
    """同一音频的处理前后两个句柄，计算实际 SNR（dB）。

    典型闭环：原始音频 → /process(add_noise) → /process(denoise) →
    对「原始 vs 加噪」与「原始 vs 降噪」各算一次，对比验证降噪有效。
    """
    clean = require_entry(request.clean_id)
    noisy = require_entry(request.noisy_id)
    try:
        value = get_provider().estimate_snr(
            dump_audio(clean.data, clean.sample_rate),
            dump_audio(noisy.data, noisy.sample_rate),
        )
    except ProviderError as exc:
        raise _provider_error(exc) from exc
    return NoiseSnrResponse(snr_db=value)
