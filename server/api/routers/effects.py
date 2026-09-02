"""效果器路由。

这里没有任何硬编码的效果名——效果清单来自注册表。
新增效果只需在 server/core/effects/ 下加文件，本文件无需改动。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from server.api.deps import require_entry
from server.core.registry import apply_effect, get_effect, list_effects
from server.schemas import ApplyEffectRequest, ApplyEffectResponse, EffectListResponse
from server.session_store import get_store

router = APIRouter(prefix="/api/effects", tags=["effects"])


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

    effect = get_effect(request.effect)
    label = f"{entry.label or entry.audio_id} → {effect.title}"

    if request.save_as_new:
        target = store.put(result, entry.sample_rate, label=label)
    else:
        target = store.replace(request.audio_id, result, entry.sample_rate)
        target.label = label

    meta = target.to_meta()
    return ApplyEffectResponse(audio_id=meta.audio_id, meta=meta)
