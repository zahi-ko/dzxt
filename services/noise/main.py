"""语音加噪与降噪子服务 · FastAPI 入口。

职责单一：可调信噪比加噪 + 谱减法降噪 + SNR 评估。无状态、不落盘、不含模型。
主干（dzxt）经 NoiseProvider 抽象层以 HTTP 对接；本服务独立 git、独立 venv，
可单独开发与部署，离线时主干仅失去加噪/降噪能力，基础功能不受影响。

启动（详见 README / AGENT.md §3.5）：
    cd services/noise
    .venv/Scripts/python.exe main.py
"""

from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import ValidationError

from app.audio import (
    add_noise_audio,
    channels_of,
    decode_wav,
    denoise_audio,
    encode_wav,
)
from app.config import HOST, MAX_UPLOAD_BYTES, PORT
from app.dsp import estimate_snr
from app.schemas import (
    AddNoiseParams,
    DenoiseParams,
    HealthResponse,
    OperationInfo,
    OperationListResponse,
    SnrResponse,
)

app = FastAPI(
    title="语音加噪与降噪子服务",
    description="可调信噪比加噪 + 谱减法（Spectral Subtraction）降噪，无状态 HTTP 服务",
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

OPERATIONS: list[OperationInfo] = [
    OperationInfo(
        name="add_noise",
        title="加噪",
        description="按目标信噪比叠加白噪声 / 粉噪声 / 布朗噪声，用于构造带噪语音",
        params_schema=AddNoiseParams.model_json_schema(),
    ),
    OperationInfo(
        name="denoise",
        title="谱减降噪",
        description="谱减法降噪：估计噪声功率谱并从带噪谱中减去，保留原始相位重建",
        params_schema=DenoiseParams.model_json_schema(),
    ),
]


def _validate(model, values: dict):
    """表单值 → Pydantic 校验。失败映射 422（与主干 apply_effect 一致）。"""
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


def _read_limited(file: UploadFile) -> bytes:
    payload = file.file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大（{len(payload)} > {MAX_UPLOAD_BYTES} 字节）",
        )
    return payload


def _decode(file: UploadFile) -> tuple:
    payload = _read_limited(file)
    try:
        return decode_wav(payload)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc


@app.get("/health", response_model=HealthResponse, summary="健康检查")
def health() -> HealthResponse:
    return HealthResponse(status="ok", operations=len(OPERATIONS))


@app.get("/operations", response_model=OperationListResponse, summary="列出操作与参数结构")
def list_operations() -> OperationListResponse:
    return OperationListResponse(items=OPERATIONS)


@app.post("/add-noise", summary="加噪：按目标 SNR 叠加噪声，返回 WAV 字节")
def add_noise_endpoint(
    file: UploadFile = File(...),
    snr_db: float = Form(default=10.0),
    noise_type: str = Form(default="white"),
    seed: int | None = Form(default=None),
) -> Response:
    params = _validate(AddNoiseParams, {"snr_db": snr_db, "noise_type": noise_type, "seed": seed})
    data, sr = _decode(file)
    out = add_noise_audio(data, sr, params.snr_db, params.noise_type, params.seed)
    return Response(content=encode_wav(out, sr), media_type="audio/wav")


@app.post("/denoise", summary="谱减降噪，返回 WAV 字节")
def denoise_endpoint(
    file: UploadFile = File(...),
    frame_ms: float = Form(default=25.0),
    hop_ms: float = Form(default=10.0),
    alpha: float = Form(default=2.0),
    beta: float = Form(default=0.02),
    noise_est_ratio: float = Form(default=0.15),
    noise_frames: int | None = Form(default=None),
    gain_smooth: float = Form(default=0.5),
) -> Response:
    params = _validate(
        DenoiseParams,
        {
            "frame_ms": frame_ms,
            "hop_ms": hop_ms,
            "alpha": alpha,
            "beta": beta,
            "noise_est_ratio": noise_est_ratio,
            "noise_frames": noise_frames,
            "gain_smooth": gain_smooth,
        },
    )
    data, sr = _decode(file)
    out = denoise_audio(
        data,
        sr,
        frame_ms=params.frame_ms,
        hop_ms=params.hop_ms,
        alpha=params.alpha,
        beta=params.beta,
        noise_est_ratio=params.noise_est_ratio,
        noise_frames=params.noise_frames,
        gain_smooth=params.gain_smooth,
    )
    return Response(content=encode_wav(out, sr), media_type="audio/wav")


@app.post("/snr", response_model=SnrResponse, summary="计算 noisy 相对 clean 的实际信噪比（dB）")
def snr_endpoint(
    clean: UploadFile = File(...),
    noisy: UploadFile = File(...),
) -> SnrResponse:
    clean_data, clean_sr = _decode(clean)
    noisy_data, noisy_sr = _decode(noisy)
    if clean_sr != noisy_sr:
        raise HTTPException(
            status_code=422,
            detail=f"采样率不一致（clean={clean_sr}, noisy={noisy_sr}），无法对比",
        )
    if channels_of(clean_data) != channels_of(noisy_data):
        raise HTTPException(
            status_code=422,
            detail="声道数不一致，无法对比（应为同一音频的处理前后版本）",
        )
    return SnrResponse(snr_db=estimate_snr(clean_data, noisy_data))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
