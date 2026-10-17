from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from synctohdd.db.database import get_db
from synctohdd.db import crud

router = APIRouter(prefix="/api/runs", tags=["Run History"])

@router.get("", response_model=Dict[str, Any])
async def list_runs(
    pair_id: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve paginated sync run history."""
    runs, total = await crud.get_sync_runs(
        session=db,
        pair_id=pair_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "runs": [
            {
                "run_id": r.run_id,
                "sync_pair_id": r.sync_pair_id,
                "sync_pair_name": r.sync_pair_name,
                "source": r.source,
                "destination": r.destination,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "status": r.status,
                "files_added": r.files_added,
                "files_modified": r.files_modified,
                "files_deleted": r.files_deleted,
                "files_unchanged": r.files_unchanged,
                "bytes_transferred": r.bytes_transferred,
                "dry_run": r.dry_run,
                "error_log": r.error_log,
            }
            for r in runs
        ],
    }

@router.get("/dashboard/stats", response_model=Dict[str, Any])
async def get_dashboard_summary(db: AsyncSession = Depends(get_db)):
    """Retrieve aggregated stats for dashboard cards."""
    data = await crud.get_dashboard_stats(db)
    recent = [
        {
            "run_id": r.run_id,
            "sync_pair_id": r.sync_pair_id,
            "sync_pair_name": r.sync_pair_name,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "status": r.status,
            "files_added": r.files_added,
            "files_modified": r.files_modified,
            "files_deleted": r.files_deleted,
            "bytes_transferred": r.bytes_transferred,
            "dry_run": r.dry_run,
        }
        for r in data["recent_runs"]
    ]
    return {
        "total_runs": data["total_runs"],
        "completed_runs": data["completed_runs"],
        "failed_runs": data["failed_runs"],
        "total_bytes_transferred": data["total_bytes_transferred"],
        "recent_runs": recent,
    }

@router.get("/{run_id}", response_model=Dict[str, Any])
async def get_run_detail(run_id: str, db: AsyncSession = Depends(get_db)):
    """Get single run summary and metadata."""
    run = await crud.get_sync_run(db, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    return {
        "run_id": run.run_id,
        "sync_pair_id": run.sync_pair_id,
        "sync_pair_name": run.sync_pair_name,
        "source": run.source,
        "destination": run.destination,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "status": run.status,
        "files_added": run.files_added,
        "files_modified": run.files_modified,
        "files_deleted": run.files_deleted,
        "files_unchanged": run.files_unchanged,
        "bytes_transferred": run.bytes_transferred,
        "dry_run": run.dry_run,
        "error_log": run.error_log,
    }

@router.get("/{run_id}/changes", response_model=Dict[str, Any])
async def get_run_changes(
    run_id: str,
    action: Optional[str] = Query(None, description="added, modified, deleted, unchanged, error"),
    search: Optional[str] = Query(None, description="Search file path"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get file changes for a specific run."""
    run = await crud.get_sync_run(db, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    changes, total = await crud.get_file_changes(
        session=db,
        run_id=run_id,
        action=action,
        search=search,
        limit=limit,
        offset=offset,
    )

    return {
        "run_id": run_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "changes": [
            {
                "change_id": c.change_id,
                "action": c.action,
                "file_path": c.file_path,
                "file_size": c.file_size,
                "source_mtime": c.source_mtime.isoformat() if c.source_mtime else None,
                "error": c.error,
            }
            for c in changes
        ],
    }

@router.delete("/{run_id}", response_model=Dict[str, Any])
async def delete_run(run_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a run record and its file changes."""
    deleted = await crud.delete_sync_run(db, run_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return {"message": f"Run '{run_id}' deleted successfully"}
