"""语音加噪与降噪子服务 · Pydantic 模型。

契约镜像自用户提供的 n1.py 参数表；主干（dzxt）侧的对应模型在
server/schemas.py，两边靠 HTTP + JSON 对接，不共享代码。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

NoiseType = Literal["white", "pink", "brown"]


class AddNoiseParams(BaseModel):
    """加噪参数。snr_db 为目标信噪比，越大越干净。"""

    snr_db: float = Field(default=10.0, ge=-5.0, le=60.0, description="目标信噪比（dB）")
    noise_type: NoiseType = Field(default="white", description="噪声类型：white/pink/brown")
    seed: int | None = Field(default=None, ge=0, description="随机种子，便于复现；缺省随机")


class DenoiseParams(BaseModel):
    """谱减降噪参数。默认值与 n1.py 一致。"""

    frame_ms: float = Field(default=25.0, ge=10.0, le=60.0, description="帧长（毫秒）")
    hop_ms: float = Field(default=10.0, ge=2.5, le=30.0, description="帧移（毫秒）")
    alpha: float = Field(default=2.0, ge=0.0, le=5.0, description="过减因子，越大降噪越狠")
    beta: float = Field(default=0.02, ge=0.0, le=0.5, description="谱底系数，防止谱减过度")
    noise_est_ratio: float = Field(
        default=0.15, ge=0.01, le=0.5, description="噪声估计取能量最低帧的比例"
    )
    noise_frames: int | None = Field(
        default=None, ge=1, description="指定用前 N 帧估计噪声谱；缺省用自适应方式"
    )
    gain_smooth: float = Field(
        default=0.5, ge=0.0, le=0.99, description="增益时间平滑系数，抑制音乐噪声"
    )


class HealthResponse(BaseModel):
    status: str
    operations: int


class OperationInfo(BaseModel):
    """操作描述。前端据此动态生成参数表单（与主干效果器注册表同思路）。"""

    name: str
    title: str
    description: str
    params_schema: dict


class OperationListResponse(BaseModel):
    items: list[OperationInfo]


class SnrResponse(BaseModel):
    snr_db: float
