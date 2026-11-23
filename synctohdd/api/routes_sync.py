from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from typing import Optional, Dict, Any
from synctohdd.config import load_config
from synctohdd.engine.manager import sync_manager

router = APIRouter(prefix="/api/sync", tags=["Sync Operations"])

class SyncRequest(BaseModel):
    dry_run: bool = False
    queue: bool = False

@router.get("/status", response_model=Dict[str, Any])
def get_sync_status():
    """Get active sync engine status, queue, and current progress."""
    return sync_manager.get_status()

@router.get("/queue", response_model=Dict[str, Any])
def get_sync_queue():
    """Get the ordered list of currently queued sync jobs."""
    queue = sync_manager.get_queue()
    return {
        "queue": queue,
        "total": len(queue),
    }

@router.delete("/queue/{job_id}", response_model=Dict[str, Any])
def remove_from_sync_queue(job_id: str):
    """Remove a specific job from the sync queue by its job_id."""
    removed = sync_manager.remove_from_queue(job_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Queued job '{job_id}' not found",
        )
    return {
        "message": f"Job for '{removed.pair_name}' removed from queue",
        "job_id": removed.job_id,
        "pair_id": removed.pair_id,
        "pair_name": removed.pair_name,
        "remaining_queue_length": len(sync_manager.get_queue()),
    }

@router.delete("/queue", response_model=Dict[str, Any])
def clear_sync_queue():
    """Clear all pending jobs from the sync queue."""
    cleared_count = sync_manager.clear_queue()
    return {
        "message": f"Successfully cleared {cleared_count} job(s) from the sync queue",
        "cleared_count": cleared_count,
    }

@router.post("/all", response_model=Dict[str, Any])
async def trigger_sync_all(
    req: SyncRequest = SyncRequest(),
    queue: Optional[bool] = Query(None, description="Queue sync jobs if engine is busy"),
):
    """Trigger sync for all configured pairs sequentially, with an option to queue if already running."""
    should_queue = queue if queue is not None else req.queue
    try:
        result = await sync_manager.start_sync_all_jobs(dry_run=req.dry_run, queue=should_queue)
        return result
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

@router.post("/{pair_id}", response_model=Dict[str, Any])
async def trigger_sync_pair(
    pair_id: str,
    req: SyncRequest = SyncRequest(),
    queue: Optional[bool] = Query(None, description="Queue sync job if engine is busy"),
):
    """Trigger a sync for a specific pair, with an option to queue if already running."""
    config = load_config()
    pair = config.get_pair_by_id(pair_id)
    if not pair:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sync pair '{pair_id}' not found",
        )

    should_queue = queue if queue is not None else req.queue
    try:
        result = await sync_manager.request_sync_job(
            pair=pair,
            dry_run=req.dry_run,
            queue=should_queue,
            config=config,
        )
        return result
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

@router.delete("/active", response_model=Dict[str, Any])
def cancel_active_sync(
    clear_queue: bool = Query(True, description="Whether to also clear all pending queued jobs"),
):
    """Cancel the currently running sync process, optionally clearing queued jobs."""
    cancelled = sync_manager.cancel_current_sync(clear_queue=clear_queue)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No sync is currently running",
        )
    return {
        "message": "Sync cancellation requested",
        "cleared_queue": clear_queue,
    }
