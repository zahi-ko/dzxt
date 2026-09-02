"""效果器注册表。

这是支撑多人并行开发的核心机制：新增一个语音处理算法，
只需要在一个新文件里写一个纯函数并加上装饰器，
路由层、参数校验、前端表单全部自动生效，无需改动任何既有文件。

约定（写给后续 session 的 Agent）：
1. 效果函数签名固定为 (x: np.ndarray, sr: int, params: ParamsModel) -> np.ndarray
2. 必须是纯函数：不读写全局状态、不做文件 IO、不播放声音
3. 输入输出都是 float32，值域 [-1, 1]
4. params 的类型注解决定前端自动生成的表单结构
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import get_type_hints

import numpy as np
from pydantic import BaseModel

from server.schemas import EffectInfo, EmptyParams

EffectFn = Callable[[np.ndarray, int, BaseModel], np.ndarray]


@dataclass(frozen=True)
class EffectDef:
    name: str
    title: str
    description: str
    params_model: type[BaseModel]
    fn: EffectFn


_REGISTRY: dict[str, EffectDef] = {}


def register_effect(*, name: str, title: str, description: str = "") -> Callable[[EffectFn], EffectFn]:
    """把一个纯函数注册为可通过 API 调用的效果器。

    params 模型从函数签名第三个参数的类型注解自动提取。
    """

    def wrapper(fn: EffectFn) -> EffectFn:
        if name in _REGISTRY:
            raise ValueError(f"效果器重复注册: {name}")

        # 效果文件普遍带 `from __future__ import annotations`，注解会被延迟成字符串，
        # 因此必须用 get_type_hints 真实求值，而不是读 signature 上的字面量。
        try:
            hints = get_type_hints(fn)
        except Exception:  # 注解无法解析时退化为无参数效果，不让注册流程中断
            hints = {}

        params_model = hints.get("params", EmptyParams)
        if not (isinstance(params_model, type) and issubclass(params_model, BaseModel)):
            params_model = EmptyParams

        _REGISTRY[name] = EffectDef(
            name=name,
            title=title,
            description=description,
            params_model=params_model,
            fn=fn,
        )
        return fn

    return wrapper


def get_effect(name: str) -> EffectDef:
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(空)"
        raise KeyError(f"未注册的效果器: {name}。已注册: {available}")
    return _REGISTRY[name]


def list_effects() -> list[EffectInfo]:
    return [
        EffectInfo(
            name=definition.name,
            title=definition.title,
            description=definition.description,
            params_schema=definition.params_model.model_json_schema(),
        )
        for definition in _REGISTRY.values()
    ]


def apply_effect(name: str, x: np.ndarray, sr: int, params: dict | None = None) -> np.ndarray:
    """统一调用入口：完成参数校验、纯函数调用与输出规范化。"""
    definition = get_effect(name)
    validated = definition.params_model.model_validate(params or {})

    result = definition.fn(np.asarray(x, dtype=np.float32), int(sr), validated)
    result = np.asarray(result, dtype=np.float32)

    if result.ndim not in (1, 2):
        raise ValueError(f"效果器 {name} 返回了非法维度: {result.ndim}")
    return np.clip(result, -1.0, 1.0)
