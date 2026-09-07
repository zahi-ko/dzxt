"""音频资源路由：列表、上传、录音、播放、波形、下载、删除。

严格遵守句柄制：除导出下载外，任何接口都不搬运波形本体。
"""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from server.api.deps import require_entry
from server.core.analysis.spectrum import waveform_envelope
from server.core.io.audio_file import dump_audio, load_audio
from server.core.io.device import DeviceError, get_player, get_recorder, list_input_devices
from server.schemas import (
    AudioListResponse,
    AudioMeta,
    DeviceListResponse,
    RecordStartRequest,
    RecordStatusResponse,
    WaveformResponse,
)
from server.session_store import get_store

router = APIRouter(prefix="/api/audio", tags=["audio"])

_RANGE_PATTERN = re.compile(r"bytes=(\d*)-(\d*)")


def _serve_wav(request: Request, wav: bytes, audio_id: str, disposition: str) -> Response:
    """按 HTTP Range 语义返回 WAV 字节。

    没有 Range 支持（206 分段响应）时，浏览器会把流视为不可 seek，
    波形单击定位与进度条拖动都会失效——游标被 timeupdate 拉回原位。
    """
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'{disposition}; filename="{audio_id}.wav"',
    }
    match = _RANGE_PATTERN.fullmatch(request.headers.get("range", "").strip())
    if not match:
        return Response(content=wav, media_type="audio/wav", headers=headers)

    total = len(wav)
    start_text, end_text = match.groups()
    if start_text == "":
        # bytes=-N：取最后 N 字节
        start = max(0, total - int(end_text))
        end = total - 1
    else:
        start = int(start_text)
        end = int(end_text) if end_text else total - 1

    if start >= total or start > end:
        return Response(
            status_code=416,
            headers={**headers, "Content-Range": f"bytes */{total}"},
        )

    end = min(end, total - 1)
    return Response(
        content=wav[start : end + 1],
        status_code=206,
        media_type="audio/wav",
        headers={**headers, "Content-Range": f"bytes {start}-{end}/{total}"},
    )


@router.get("", response_model=AudioListResponse, summary="列出全部音频句柄")
def list_audio() -> AudioListResponse:
    return AudioListResponse(items=[entry.to_meta() for entry in get_store().list()])


@router.get("/devices", response_model=DeviceListResponse, summary="列出可用输入设备")
def list_devices() -> DeviceListResponse:
    items, default_index = list_input_devices()
    return DeviceListResponse(items=items, default_index=default_index)


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
        recorder.start(
            sample_rate=request.sample_rate,
            channels=request.channels,
            duration=request.duration,
            device=request.device,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DeviceError as exc:
        # 无麦克风 / 设备被占用都归到这里：这是环境问题，不是请求错误
        raise HTTPException(status_code=503, detail=str(exc)) from exc
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

    # 多次录音全叫「录音」无法区分，用结束时刻命名
    label = f"录音 {datetime.now():%H:%M:%S}"
    entry = get_store().put(data, sample_rate, label=label)
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


@router.get("/{audio_id}/stream", summary="以 WAV 流形式返回音频，供前端播放器直接播放")
def stream_audio(audio_id: str, request: Request) -> Response:
    """与 download 的区别只有 Content-Disposition：这里是 inline，浏览器直接播放。

    支持 HTTP Range（206）：浏览器 media 元素依赖它做 seek，
    缺失时单击定位与拖动进度条都不会生效。

    前端播放是必要的：sounddevice 的 sd.play 拿不到播放位置，
    做不了进度条、暂停续播与变速，见 docs/adr/0007-frontend-playback.md。
    """
    entry = require_entry(audio_id)
    wav = dump_audio(entry.data, entry.sample_rate)
    return _serve_wav(request, wav, audio_id, disposition="inline")


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
