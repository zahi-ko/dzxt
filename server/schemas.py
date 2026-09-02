"""跨模块共享契约层。

本文件是全系统唯一接口真相源。任何 Agent 修改这里的模型定义，
都必须同步更新 AGENT.md 的数据契约章节并通知全组。

设计约束：
1. 内部音频一律为 float32 ndarray，值域 [-1, 1]，单声道为一维数组 (n,)，
   多声道为二维数组 (n, channels)。禁止在模块间传递 WAV bytes / base64。
2. API 层只传递 audio_id 句柄，永不搬运波形数据。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

DEFAULT_SAMPLE_RATE = 16000
SUPPORTED_SAMPLE_RATES = (8000, 16000, 22050, 44100, 48000)


class EmptyParams(BaseModel):
    """无参数效果的占位模型。"""


class AudioMeta(BaseModel):
    """音频句柄的元数据。波形本体只存在于后端 SessionStore。"""

    audio_id: str
    sample_rate: int
    channels: int
    duration: float
    created_at: datetime
    label: str = ""


class AudioListResponse(BaseModel):
    items: list[AudioMeta]


class RecordStartRequest(BaseModel):
    duration: float | None = Field(default=None, ge=0.1, le=300, description="最长录音秒数，None 表示手动停止")
    sample_rate: int = Field(default=DEFAULT_SAMPLE_RATE)


class RecordStatusResponse(BaseModel):
    recording: bool
    elapsed: float
    level: float = Field(default=0.0, description="当前帧 RMS 电平，用于前端实时电平条")


class EffectInfo(BaseModel):
    """效果器描述。前端据此动态生成参数表单。"""

    name: str
    title: str
    description: str
    params_schema: dict


class EffectListResponse(BaseModel):
    items: list[EffectInfo]


class ApplyEffectRequest(BaseModel):
    audio_id: str
    effect: str = Field(description="效果器注册名，如 reverse / gain")
    params: dict = Field(default_factory=dict)
    save_as_new: bool = Field(default=True, description="True 生成新句柄，False 覆盖原句柄")


class ApplyEffectResponse(BaseModel):
    audio_id: str
    meta: AudioMeta


class SpectrumRequest(BaseModel):
    audio_id: str
    n_fft: int = Field(default=1024, ge=128, le=8192)


class SpectrumResponse(BaseModel):
    audio_id: str
    sample_rate: int
    freqs: list[float]
    magnitude_db: list[float]


class WaveformResponse(BaseModel):
    """波形包络。

    前端用 min/max 两列即可画出与原始采样点视觉等价的波形，
    避免把几十万个采样点搬到浏览器。
    """

    audio_id: str
    sample_rate: int
    duration: float
    points: int
    minimum: list[float]
    maximum: list[float]


class ErrorResponse(BaseModel):
    detail: str
