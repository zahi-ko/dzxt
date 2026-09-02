"""音频资源路由：列表、上传、录音、播放、波形、下载、删除。

严格遵守句柄制：除导出下载外，任何接口都不搬运波形本体。
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from server.api.deps import require_entry
from server.core.analysis.spectrum import waveform_envelope
from server.core.io.audio_file import dump_audio, load_audio
from server.core.io.device import get_player, get_recorder
from server.schemas import (
    AudioListResponse,
    AudioMeta,
    RecordStartRequest,
    RecordStatusResponse,
    WaveformResponse,
)
from server.session_store import get_store

router = APIRouter(prefix="/api/audio", tags=["audio"])


@router.get("", response_model=AudioListResponse, summary="列出全部音频句柄")
def list_audio() -> AudioListResponse:
    return AudioListResponse(items=[entry.to_meta() for entry in get_store().list()])


@router.post("/upload", response_model=AudioMeta, summary="上传音频文件")
async def upload_audio(file: UploadFile = File(...)) -> AudioMeta:
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="上传文件为空")

    try:
        data, sample_rate = load_audio(payload)
    except Exception as exc:  # soundfile 的异常类型不统一，统一收敛为 415
        raise HTTPException(status_code=415, detail=f"无法解码音频文件: {exc}") from exc

    entry = get_store().put(data, sample_rate, label=file.filename or "上传音频")
    return entry.to_meta()


@router.post("/record/start", response_model=RecordStatusResponse, summary="开始录音")
def start_record(request: RecordStartRequest) -> RecordStatusResponse:
    recorder = get_recorder()
    try:
        recorder.start(sample_rate=request.sample_rate, channels=1, duration=request.duration)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RecordStatusResponse(recording=True, elapsed=0.0, level=0.0)


@router.get("/record/status", response_model=RecordStatusResponse, summary="查询录音状态与电平")
def record_status() -> RecordStatusResponse:
    recorder = get_recorder()
    return RecordStatusResponse(
        recording=recorder.recording,
        elapsed=recorder.elapsed,
        level=recorder.level,
    )


@router.post("/record/stop", response_model=AudioMeta, summary="停止录音并生成句柄")
def stop_record() -> AudioMeta:
    recorder = get_recorder()
    try:
        data, sample_rate = recorder.stop()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if data.size == 0:
        raise HTTPException(status_code=422, detail="未采集到音频数据，请检查麦克风设备")

    entry = get_store().put(data, sample_rate, label="录音")
    return entry.to_meta()


@router.get(
    "/{audio_id}/peaks",
    response_model=WaveformResponse,
    summary="获取波形包络用于绘制",
)
def get_peaks(
    audio_id: str,
    points: int = Query(default=2000, ge=100, le=20000, description="包络点数"),
) -> WaveformResponse:
    entry = require_entry(audio_id)
    minimum, maximum = waveform_envelope(entry.data, points=points)
    return WaveformResponse(
        audio_id=audio_id,
        sample_rate=entry.sample_rate,
        duration=entry.duration,
        points=len(minimum),
        minimum=minimum,
        maximum=maximum,
    )


@router.post("/{audio_id}/play", status_code=204, summary="后端播放音频")
def play_audio(audio_id: str) -> Response:
    entry = require_entry(audio_id)
    get_player().play(entry.data, entry.sample_rate)
    return Response(status_code=204)


@router.post("/play/stop", status_code=204, summary="停止播放")
def stop_play() -> Response:
    get_player().stop()
    return Response(status_code=204)


@router.get("/{audio_id}/download", summary="导出为 WAV")
def download_audio(audio_id: str) -> Response:
    entry = require_entry(audio_id)
    wav = dump_audio(entry.data, entry.sample_rate)
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={"Content-Disposition": f'attachment; filename="{audio_id}.wav"'},
    )


@router.delete("/{audio_id}", status_code=204, summary="释放音频句柄")
def delete_audio(audio_id: str) -> Response:
    require_entry(audio_id)
    get_store().delete(audio_id)
    return Response(status_code=204)
