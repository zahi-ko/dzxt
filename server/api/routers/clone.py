"""语音克隆路由（3.1）。

主干不接触引擎与适配层的任何实现细节，全部经由 TTSProvider；
克隆产物直接写入 SessionStore——因此「克隆结果回流音频列表、
可继续施加效果」无需任何额外代码，血统链也天然成立。
"""

from __future__ import annotations

import io
from urllib.parse import quote

import soundfile as sf
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from server.schemas import (
    CloneRefListResponse,
    CloneRefMeta,
    CloneRefPromptUpdate,
    CloneStatusResponse,
    CloneSynthesizeRequest,
    CloneSynthesizeResponse,
)
from server.session_store import get_store
from server.tts_provider import ProviderError, get_provider

router = APIRouter(prefix="/api/clone", tags=["clone"])

# 引擎离线时的统一提示。真实原因（哪个环节不可达）在 status/detail 里可查。
_OFFLINE_HINT = "克隆子服务未就绪，请先启动适配层与引擎（见 AGENT.md §3.4）"


def _provider_error(exc: ProviderError) -> HTTPException:
    status = exc.status_code if exc.status_code in (400, 404, 502) else 503
    detail = str(exc)
    if status == 503:
        detail = f"{_OFFLINE_HINT}（{detail}）"
    return HTTPException(status_code=status, detail=detail)


@router.get("/status", response_model=CloneStatusResponse, summary="克隆链路状态")
def status() -> CloneStatusResponse:
    """探活失败永远返回 200 + online=false，让前端从容展示离线态。"""
    try:
        return get_provider().health()
    except Exception:  # ProviderError 及一切意外都不应影响前端渲染
        return CloneStatusResponse(adapter_online=False, adapter_detail="探活异常")


@router.get("/refs", response_model=CloneRefListResponse, summary="列出参考音频")
def list_refs() -> CloneRefListResponse:
    try:
        return CloneRefListResponse(items=get_provider().list_refs())
    except ProviderError as exc:
        raise _provider_error(exc) from exc


@router.post("/refs", response_model=CloneRefMeta, status_code=201, summary="上传参考音频")
def upload_ref(
    file: UploadFile = File(...),
    prompt_text: str = Form(default=""),
) -> CloneRefMeta:
    try:
        return get_provider().upload_ref(
            file.file.read(), file.filename or "", prompt_text
        )
    except ProviderError as exc:
        raise _provider_error(exc) from exc


@router.patch("/refs/{ref_id}", response_model=CloneRefMeta, summary="修改参考文本")
def update_ref(ref_id: str, body: CloneRefPromptUpdate) -> CloneRefMeta:
    try:
        return get_provider().update_ref_prompt(ref_id, body.prompt_text)
    except ProviderError as exc:
        raise _provider_error(exc) from exc


@router.delete("/refs/{ref_id}", status_code=204, summary="删除参考音频")
def delete_ref(ref_id: str) -> None:
    try:
        get_provider().delete_ref(ref_id)
    except ProviderError as exc:
        raise _provider_error(exc) from exc


@router.get("/refs/{ref_id}/export", summary="导出音色为 .clone 文件")
def export_ref(ref_id: str) -> Response:
    """参考音频 + 参考文本 + 预设合成文本打包为 .clone（ZIP 容器），不含模型权重。"""
    provider = get_provider()
    try:
        payload = provider.export_ref(ref_id)
        refs = {r.ref_id: r for r in provider.list_refs()}
        record = refs.get(ref_id)
    except ProviderError as exc:
        raise _provider_error(exc) from exc

    voice_name = record.filename.rsplit(".", 1)[0] if record else "voice"
    suggested = f"{voice_name}.clone"
    ascii_fallback = suggested.encode("ascii", "ignore").decode() or "voice.clone"
    disposition = (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(suggested)}"
    )
    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


@router.post(
    "/refs/import", response_model=CloneRefMeta, summary="导入 .clone 音色文件"
)
def import_ref(file: UploadFile = File(...)) -> CloneRefMeta:
    try:
        return get_provider().import_ref(file.file.read(), file.filename or "")
    except ProviderError as exc:
        raise _provider_error(exc) from exc


@router.post(
    "/synthesize", response_model=CloneSynthesizeResponse, summary="克隆合成并入库"
)
def synthesize(request: CloneSynthesizeRequest) -> CloneSynthesizeResponse:
    """同步合成（4060 上一句话秒级完成），产物按句柄制入库。

    引擎输出采样率以引擎配置为准（v2 = 32kHz），解码后照实记录，
    下游效果链与播放按 AudioMeta 的 sample_rate 走，不受主干默认值影响。
    """
    provider = get_provider()
    try:
        wav = provider.synthesize(request)
    except ProviderError as exc:
        raise _provider_error(exc) from exc

    try:
        data, sr = sf.read(io.BytesIO(wav), dtype="float32")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"合成音频解码失败：{exc}") from exc

    refs = {r.ref_id: r for r in provider.list_refs()}
    ref_label = refs.get(request.ref_id).filename if request.ref_id in refs else request.ref_id
    entry = get_store().put(data, sr, label=f"克隆·{ref_label[:24]}")

    return CloneSynthesizeResponse(
        audio_id=entry.audio_id,
        meta=entry.to_meta(),
        ref_id=request.ref_id,
        text=request.text,
    )
