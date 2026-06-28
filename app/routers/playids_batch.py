from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import PlayidsBatchRequest
from app.services.playids_ncmm import run_playids_batch_via_ncmm

router = APIRouter(prefix="/api/playids", tags=["playids-batch"])


@router.post("/batch")
async def playids_batch(req: PlayidsBatchRequest):
    try:
        return await run_playids_batch_via_ncmm(
            req.config_path,
            req.only_user_ids,
            use_all_users=req.use_all_users,
            strict_user_mapping=req.strict_user_mapping,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
