"""效果器路由：单效果、效果链、撤销。

这里没有任何硬编码的效果名——效果清单来自注册表。
新增效果只需在 server/core/effects/ 下加文件，本文件无需改动。

血统约定：每次处理都在产物上记录 source_id（上一步）与 steps（从源头起的全部步骤）。
「处理历史」直接读 steps，「撤销」就是跳回 source_id 指向的上一版。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from server.api.deps import require_entry
from server.core.registry import apply_effect, get_effect, list_effects
from server.schemas import (
    ApplyEffectRequest,
    ApplyEffectResponse,
    EffectChainRequest,
    EffectChainResponse,
    EffectHistoryItem,
    EffectHistoryResponse,
    EffectListResponse,
    UndoRequest,
)
from server.session_store import get_store

router = APIRouter(prefix="/api/effects", tags=["effects"])


def _step_item(name: str, params: dict) -> EffectHistoryItem:
    effect = get_effect(name)
    return EffectHistoryItem(effect=name, title=effect.title, params=params)


@router.get("", response_model=EffectListResponse, summary="列出已注册效果器")
def list_available_effects() -> EffectListResponse:
    return EffectListResponse(items=list_effects())


@router.post("/apply", response_model=ApplyEffectResponse, summary="施加效果")
def apply_effect_api(request: ApplyEffectRequest) -> ApplyEffectResponse:
    store = get_store()
    entry = require_entry(request.audio_id)

    try:
        result = apply_effect(request.effect, entry.data, entry.sample_rate, request.params)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    steps = entry.steps + [_step_item(request.effect, request.params)]
    effect = get_effect(request.effect)
    label = f"{entry.label or entry.audio_id} → {effect.title}"

    if request.save_as_new:
        target = store.put(result, entry.sample_rate, label=label, source_id=entry.audio_id, steps=steps)
    else:
        target = store.replace(request.audio_id, result, entry.sample_rate)
        target.label = label
        target.steps = steps

    meta = target.to_meta()
    return ApplyEffectResponse(audio_id=meta.audio_id, meta=meta)


@router.post("/chain", response_model=EffectChainResponse, summary="按顺序施加效果链")
def apply_chain(request: EffectChainRequest) -> EffectChainResponse:
    """一次请求串起多个效果，产物只保留一个句柄。

    与逐个调用 /apply 的区别：不产生中间句柄，处理历史里每一步仍完整可见。
    """
    if not request.steps:
        raise HTTPException(status_code=400, detail="效果链为空")

    store = get_store()
    entry = require_entry(request.audio_id)

    data = entry.data
    sample_rate = entry.sample_rate
    steps: list[EffectHistoryItem] = list(entry.steps)
    applied: list[str] = []

    for index, step in enumerate(request.steps):
        try:
            data = apply_effect(step.effect, data, sample_rate, step.params)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"第 {index + 1} 步: {exc}") from exc
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=f"第 {index + 1} 步: {exc.errors()}") from exc
        steps.append(_step_item(step.effect, step.params))
        applied.append(get_effect(step.effect).title)

    label = f"{entry.label or entry.audio_id} → " + " → ".join(applied)
    if len(label) > 80:
        label = f"{entry.label or entry.audio_id} → {len(applied)} 步效果链"

    if request.save_as_new:
        target = store.put(data, sample_rate, label=label, source_id=entry.audio_id, steps=steps)
    else:
        target = store.replace(request.audio_id, data, sample_rate)
        target.label = label
        target.steps = steps

    meta = target.to_meta()
    return EffectChainResponse(audio_id=meta.audio_id, meta=meta, applied=applied)


@router.post("/undo", response_model=ApplyEffectResponse, summary="撤销一步处理")
def undo_effect(request: UndoRequest) -> ApplyEffectResponse:
    """回退到上一步结果。

    撤销不修改任何既有句柄，只是把上一版的句柄交回前端——
    这样处理历史天然可回溯，也不会因为撤销而破坏别人正在对比的音频。
    """
    store = get_store()
    entry = require_entry(request.audio_id)

    if not entry.steps:
        raise HTTPException(status_code=400, detail="这是原始音频，没有可撤销的处理")

    if entry.source_id is None:
        raise HTTPException(status_code=409, detail="该音频缺少上一步记录，无法撤销")

    try:
        parent = store.get(entry.source_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=409, detail=f"上一步的结果已被删除，无法撤销：{entry.source_id}"
        ) from exc

    meta = parent.to_meta()
    return ApplyEffectResponse(audio_id=meta.audio_id, meta=meta)


@router.get(
    "/{audio_id}/history",
    response_model=EffectHistoryResponse,
    summary="查看处理历史",
)
def effect_history(audio_id: str) -> EffectHistoryResponse:
    store = get_store()
    entry = require_entry(audio_id)
    root = store.root_of(audio_id)
    return EffectHistoryResponse(audio_id=audio_id, root_id=root.audio_id, steps=list(entry.steps))
