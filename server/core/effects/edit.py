"""时域编辑类效果：裁剪与淡入淡出。

裁剪让波形图上的「选区」有实际用处：前端框选一段后填进参数即可导出片段。
淡入淡出消除起止处的突变，避免播放开头/结尾的爆音。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from server.core.registry import register_effect


class TrimParams(BaseModel):
    start_sec: float = Field(default=0.0, ge=0.0, description="起始秒数")
    end_sec: float = Field(default=0.0, ge=0.0, description="结束秒数，0 表示到音频结尾")


@register_effect(
    name="trim",
    title="裁剪",
    description="按时间区间截取片段，常与波形选区配合使用",
)
def trim(x: np.ndarray, sr: int, params: TrimParams) -> np.ndarray:
    start = int(params.start_sec * sr)
    end = x.shape[0] if params.end_sec <= 0 else int(params.end_sec * sr)

    start = max(0, min(start, x.shape[0]))
    end = max(start, min(end, x.shape[0]))
    return np.ascontiguousarray(x[start:end])


class FadeParams(BaseModel):
    fade_in: float = Field(default=0.05, ge=0.0, le=5.0, description="淡入时长（秒）")
    fade_out: float = Field(default=0.05, ge=0.0, le=5.0, description="淡出时长（秒）")
    curve: float = Field(default=1.0, ge=0.2, le=4.0, description="曲线指数，1 为线性，>1 更缓")


@register_effect(
    name="fade",
    title="淡入淡出",
    description="在首尾做渐变，消除突变引起的爆音",
)
def fade(x: np.ndarray, sr: int, params: FadeParams) -> np.ndarray:
    out = np.array(x, dtype=np.float32, copy=True)
    total = out.shape[0]

    in_len = min(total, int(params.fade_in * sr))
    if in_len > 0:
        ramp = np.linspace(0.0, 1.0, in_len, dtype=np.float32) ** params.curve
        out[:in_len] *= ramp

    out_len = min(total - in_len, int(params.fade_out * sr))
    if out_len > 0:
        ramp = np.linspace(1.0, 0.0, out_len, dtype=np.float32) ** params.curve
        out[-out_len:] *= ramp

    return out
