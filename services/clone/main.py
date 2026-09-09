"""语音克隆适配层 · FastAPI 入口。

职责单一：托管参考音频文件，并把合成请求转发给 GPT-SoVITS 引擎。
不做任何模型推理——torch 只存在于引擎整合包内。

启动（详见 README / AGENT.md §3.4）：
    cd services/clone
    .venv/Scripts/python.exe main.py
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.config import HOST, PORT, TEXT_MAX_CHARS
from app.engine import EngineClient, EngineError
from app.refs import RefError, RefStore
from app.schemas import (
    HealthResponse,
    RefListResponse,
    RefMeta,
    RefPromptUpdate,
    SynthesizeRequest,
)

app = FastAPI(
    title="语音克隆适配层",
    description="主干与 GPT-SoVITS 引擎之间的轻量 HTTP 桥",
    version="0.1.0",
)

# 浏览器只与主干(8000)通信；开放 CORS 仅服务于本地调试直连场景
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = RefStore()
engine = EngineClient()


def _meta(record) -> RefMeta:
    return RefMeta(
        ref_id=record.ref_id,
        filename=record.filename,
        duration=record.duration,
        sample_rate=record.sample_rate,
        prompt_text=record.prompt_text,
        sample_text=record.sample_text,
        created_at=record.created_at,
    )


@app.get("/health", response_model=HealthResponse, summary="健康检查（含引擎探活）")
def health() -> HealthResponse:
    status = engine.health()
    return HealthResponse(
        status="ok",
        engine_online=status["online"],
        engine_detail=status["detail"],
        refs=store.count(),
    )


@app.post("/refs", response_model=RefMeta, summary="上传参考音频")
def upload_ref(
    file: UploadFile = File(...),
    prompt_text: str = Form(default=""),
) -> RefMeta:
    try:
        record = store.add(file.file.read(), file.filename or "", prompt_text)
    except RefError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _meta(record)


@app.get("/refs", response_model=RefListResponse, summary="列出参考音频")
def list_refs() -> RefListResponse:
    return RefListResponse(items=[_meta(r) for r in store.list()])


@app.patch("/refs/{ref_id}", response_model=RefMeta, summary="修改参考文本")
def update_ref(ref_id: str, body: RefPromptUpdate) -> RefMeta:
    try:
        record = store.update_prompt(ref_id, body.prompt_text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _meta(record)


@app.delete("/refs/{ref_id}", status_code=204, summary="删除参考音频")
def delete_ref(ref_id: str) -> Response:
    try:
        store.delete(ref_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@app.get("/refs/{ref_id}/export", summary="导出音色为 .clone 文件")
def export_ref(ref_id: str) -> Response:
    """ZIP 容器（voice.json + ref.wav），只含文本与参考音频，不含模型权重。"""
    try:
        payload, suggested = store.export_clone(ref_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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


@app.post("/refs/import", response_model=RefMeta, summary="导入 .clone 音色文件")
def import_ref(file: UploadFile = File(...)) -> RefMeta:
    try:
        record = store.import_clone(file.file.read(), file.filename or "")
    except RefError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _meta(record)


@app.post("/synthesize", summary="合成克隆语音，返回 WAV 字节")
def synthesize(request: SynthesizeRequest) -> Response:
    if len(request.text) > TEXT_MAX_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"文本过长（{len(request.text)} > {TEXT_MAX_CHARS} 字符），请分段合成",
        )
    try:
        record = store.get(request.ref_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    prompt_text = request.prompt_text or record.prompt_text
    batch_size = request.batch_size
    # 引擎 prompt-free（无参考文本）模式不支持 batch 并行：batch_size>1 会被
    # 降级为逐句推理并打印警告——直接归一为 1，避免无效批量与告警噪音
    if not prompt_text.strip():
        batch_size = 1

    payload = {
        "text": request.text,
        "text_lang": request.text_lang,
        "ref_audio_path": store.path_of(request.ref_id),
        "prompt_text": prompt_text,
        "prompt_lang": request.prompt_lang,
        "speed_factor": request.speed_factor,
        "text_split_method": request.text_split_method,
        "batch_size": batch_size,
        "fragment_interval": request.fragment_interval,
        "temperature": request.temperature,
        "top_k": request.top_k,
        "top_p": request.top_p,
        "repetition_penalty": request.repetition_penalty,
        "seed": request.seed,
    }
    try:
        wav = engine.synthesize(payload)
    except EngineError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # 参考文本自动回写：合成成功即证明该文本有效，持久化到参考音记录。
    # 此前参考文本只能在上传时填写，编辑框只是临时覆盖不落盘，
    # 导致导出 .clone 时打包到空文本。
    if request.prompt_text.strip() and request.prompt_text != record.prompt_text:
        try:
            store.update_prompt(request.ref_id, request.prompt_text)
        except KeyError:
            pass

    # 记录该音色最近一次合成的文本，导出 .clone 时作为预设合成文本打包
    try:
        store.update_sample_text(request.ref_id, request.text)
    except KeyError:
        pass

    return Response(content=wav, media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
