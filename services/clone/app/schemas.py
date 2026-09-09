"""适配层接口模型。

与主干 server/schemas.py 的克隆相关模型保持字段镜像；
两侧独立声明（服务边界），新增字段时必须同步修改。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RefMeta(BaseModel):
    """参考音频元数据。波形本体只存磁盘文件，接口只传 ref_id。"""

    ref_id: str
    filename: str = Field(description="展示文件名（上传后统一归一为 .wav）")
    duration: float
    sample_rate: int
    prompt_text: str = Field(default="", description="参考音频对应的文字内容")
    sample_text: str = Field(default="", description="最近一次为该音色合成的文本")
    created_at: datetime


class RefListResponse(BaseModel):
    items: list[RefMeta]


class RefPromptUpdate(BaseModel):
    prompt_text: str = Field(default="", max_length=200)


class SynthesizeRequest(BaseModel):
    """合成请求。

    prompt_text 是参考音频「说了什么」。官方强烈建议填写：
    它让引擎对齐音色与韵律，缺省时合成质量明显下降。
    其余字段默认值与引擎 api_v2 的 TTS_Request 保持一致，透传即可。
    """

    ref_id: str
    text: str = Field(min_length=1, max_length=500, description="要合成的目标文本")
    prompt_text: str = Field(default="", max_length=200, description="参考音频的文字内容")
    text_lang: str = Field(default="zh", description="目标文本语言：zh / en / ja / ko / yue / auto")
    prompt_lang: str = Field(default="zh", description="参考文本语言")
    speed_factor: float = Field(default=1.0, ge=0.5, le=2.0, description="语速倍率")
    text_split_method: str = Field(default="cut5", description="切分方式 cut0-cut5")
    batch_size: int = Field(default=1, ge=1, le=64, description="并行合成批大小")
    fragment_interval: float = Field(default=0.3, ge=0.0, le=2.0, description="句间停顿秒数")
    temperature: float = Field(default=1.0, ge=0.01, le=2.0, description="采样温度")
    top_k: int = Field(default=15, ge=1, le=200, description="top-k 采样")
    top_p: float = Field(default=1.0, gt=0.0, le=1.0, description="top-p 采样")
    repetition_penalty: float = Field(default=1.35, ge=1.0, le=10.0, description="重复惩罚")
    seed: int = Field(default=-1, ge=-1, description="随机种子，-1 为随机")


class HealthResponse(BaseModel):
    status: str
    engine_online: bool
    engine_detail: str = Field(default="", description="引擎离线时的提示信息")
    refs: int
