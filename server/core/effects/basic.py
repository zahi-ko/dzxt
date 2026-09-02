"""基础语音处理效果器。

新增效果器的完整流程（写给后续 session 的 Agent）：
    1. 在本目录新建一个文件，例如 pitch.py
    2. 定义参数模型 class XxxParams(BaseModel)
    3. 写纯函数 def xxx(x: np.ndarray, sr: int, params: XxxParams) -> np.ndarray
    4. 加装饰器 @register_effect(name="xxx", title="...", description="...")
    5. 在 server/core/effects/__init__.py 中 import 该文件
路由、参数校验、前端表单会自动生效，不需要改任何其他文件。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from server.core.registry import register_effect
from server.schemas import EmptyParams


@register_effect(name="reverse", title="倒放", description="沿时间轴反转音频，用于演示与频谱对称特性")
def reverse(x: np.ndarray, sr: int, params: EmptyParams) -> np.ndarray:
    return np.ascontiguousarray(x[::-1])


class GainParams(BaseModel):
    db: float = Field(default=0.0, ge=-60, le=24, description="增益，单位 dB")


@register_effect(name="gain", title="音量增益", description="按分贝缩放幅度，输出自动限幅到 [-1, 1]")
def gain(x: np.ndarray, sr: int, params: GainParams) -> np.ndarray:
    scale = 10.0 ** (params.db / 20.0)
    return x * np.float32(scale)


class TempoParams(BaseModel):
    speed: float = Field(default=1.0, ge=0.25, le=4.0, description="倍速系数，大于 1 为加速")


@register_effect(
    name="tempo_resample",
    title="倍速（变调）",
    description="通过重采样改变时长，音高同步变化，实现简单、无失真",
)
def tempo_resample(x: np.ndarray, sr: int, params: TempoParams) -> np.ndarray:
    from scipy.signal import resample_poly

    if abs(params.speed - 1.0) < 1e-3:
        return x.copy()

    up = 100
    down = max(1, int(round(100 * params.speed)))
    axis = 0
    return resample_poly(x, up, down, axis=axis).astype(np.float32)


@register_effect(
    name="tempo_ola",
    title="倍速（不变调）",
    description="重叠相加(OLA)时间缩放，时长改变而音高保持不变",
)
def tempo_ola(x: np.ndarray, sr: int, params: TempoParams) -> np.ndarray:
    if abs(params.speed - 1.0) < 1e-3:
        return x.copy()

    frame = int(sr * 0.05)
    if x.shape[0] < frame * 2:
        return x.copy()

    analysis_hop = frame // 2
    synthesis_hop = max(1, int(round(analysis_hop / params.speed)))
    window = np.hanning(frame).astype(np.float32)

    n_frames = max(1, (x.shape[0] - frame) // analysis_hop + 1)
    out_len = (n_frames - 1) * synthesis_hop + frame
    out = np.zeros(out_len, dtype=np.float32)
    weight = np.zeros(out_len, dtype=np.float32)

    for i in range(n_frames):
        start = i * analysis_hop
        segment = x[start : start + frame] * window
        pos = i * synthesis_hop
        out[pos : pos + frame] += segment
        weight[pos : pos + frame] += window

    np.maximum(weight, 1e-6, out=weight)
    return out / weight


class NormalizeParams(BaseModel):
    peak_db: float = Field(default=-3.0, ge=-24, le=0, description="归一化目标峰值，单位 dB")


@register_effect(name="normalize", title="峰值归一化", description="将峰值电平调整到指定分贝")
def normalize(x: np.ndarray, sr: int, params: NormalizeParams) -> np.ndarray:
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak < 1e-9:
        return x.copy()
    target = 10.0 ** (params.peak_db / 20.0)
    return x * np.float32(target / peak)
