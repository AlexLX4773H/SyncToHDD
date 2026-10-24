from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional, Dict, Any
from synctohdd.config import load_config
from synctohdd.engine.manager import sync_manager

router = APIRouter(prefix="/api/sync", tags=["Sync Operations"])

class SyncRequest(BaseModel):
    dry_run: bool = False

@router.get("/status", response_model=Dict[str, Any])
def get_sync_status():
    """Get active sync engine status and current progress."""
    return sync_manager.get_status()

@router.post("/all", response_model=Dict[str, Any])
async def trigger_sync_all(req: SyncRequest = SyncRequest()):
    """Trigger sync for all configured pairs sequentially."""
    try:
        queued_pairs = await sync_manager.start_sync_all_jobs(dry_run=req.dry_run)
        return {
            "status": "started",
            "queued_pairs": queued_pairs,
            "dry_run": req.dry_run,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

@router.post("/{pair_id}", response_model=Dict[str, Any])
async def trigger_sync_pair(pair_id: str, req: SyncRequest = SyncRequest()):
    """Trigger a sync for a specific pair."""
    config = load_config()
    pair = config.get_pair_by_id(pair_id)
    if not pair:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sync pair '{pair_id}' not found",
        )

    try:
        run_id = await sync_manager.start_sync_job(pair, dry_run=req.dry_run, config=config)
        return {
            "status": "started",
            "run_id": run_id,
            "pair_id": pair.id,
            "pair_name": pair.name,
            "dry_run": req.dry_run,
        }
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

@router.delete("/active", response_model=Dict[str, Any])
def cancel_active_sync():
    """Cancel the currently running sync process."""
    cancelled = sync_manager.cancel_current_sync()
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No sync is currently running",
        )
    return {"message": "Sync cancellation requested"}
