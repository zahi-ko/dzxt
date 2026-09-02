"""分析路由：频谱与音频统计。"""

from __future__ import annotations

from fastapi import APIRouter

from server.api.deps import require_entry
from server.core.analysis.spectrum import average_spectrum, peak_level, rms_level
from server.schemas import SpectrumRequest, SpectrumResponse

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


@router.get("/{audio_id}/stats", summary="音频统计信息")
def stats(audio_id: str) -> dict:
    entry = require_entry(audio_id)
    return {
        "audio_id": audio_id,
        "sample_rate": entry.sample_rate,
        "channels": entry.channels,
        "duration": entry.duration,
        "rms": rms_level(entry.data),
        "peak": peak_level(entry.data),
    }
