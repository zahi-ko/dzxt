"""分析路由：频谱与音频统计。"""

from __future__ import annotations

from fastapi import APIRouter

from server.api.deps import require_entry
from server.core.analysis.spectrogram import quantize_db, stft_magnitude_db
from server.core.analysis.spectrum import average_spectrum, peak_level, rms_level
from server.schemas import (
    AudioStatsResponse,
    SpectrogramRequest,
    SpectrogramResponse,
    SpectrumRequest,
    SpectrumResponse,
)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.post("/spectrum", response_model=SpectrumResponse, summary="计算平均幅度谱")
def spectrum(request: SpectrumRequest) -> SpectrumResponse:
    entry = require_entry(request.audio_id)
    freqs, magnitude_db = average_spectrum(entry.data, entry.sample_rate, n_fft=request.n_fft)

    return SpectrumResponse(
        audio_id=request.audio_id,
        sample_rate=entry.sample_rate,
        freqs=freqs.tolist(),
        magnitude_db=magnitude_db.tolist(),
    )


@router.post("/spectrogram", response_model=SpectrogramResponse, summary="计算语谱图（STFT 热力图）")
def spectrogram(request: SpectrogramRequest) -> SpectrogramResponse:
    entry = require_entry(request.audio_id)
    magnitude_db, times, freqs = stft_magnitude_db(
        entry.data,
        entry.sample_rate,
        n_fft=request.n_fft,
        max_frames=request.max_frames,
    )
    quantized = quantize_db(magnitude_db, request.floor_db, request.ceiling_db)

    return SpectrogramResponse(
        audio_id=request.audio_id,
        sample_rate=entry.sample_rate,
        times=times.tolist(),
        freqs=freqs.tolist(),
        frames=int(quantized.shape[0]),
        bins=int(quantized.shape[1]),
        data=quantized.reshape(-1).tolist(),
        floor_db=request.floor_db,
        ceiling_db=request.ceiling_db,
    )


@router.get(
    "/{audio_id}/stats",
    response_model=AudioStatsResponse,
    summary="音频统计信息",
)
def stats(audio_id: str) -> AudioStatsResponse:
    entry = require_entry(audio_id)
    return AudioStatsResponse(
        audio_id=audio_id,
        sample_rate=entry.sample_rate,
        channels=entry.channels,
        duration=entry.duration,
        rms=rms_level(entry.data),
        peak=peak_level(entry.data),
    )
