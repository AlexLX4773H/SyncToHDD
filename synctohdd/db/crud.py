from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy import select, func, desc, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from synctohdd.db.models import SyncRun, FileChange

async def create_sync_run(
    session: AsyncSession,
    run_id: str,
    sync_pair_id: str,
    sync_pair_name: str,
    source: str,
    destination: str,
    dry_run: bool = False,
) -> SyncRun:
    """Create a new sync run record in 'running' state."""
    run = SyncRun(
        run_id=run_id,
        sync_pair_id=sync_pair_id,
        sync_pair_name=sync_pair_name,
        source=source,
        destination=destination,
        started_at=datetime.now(timezone.utc),
        status="running",
        dry_run=dry_run,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run

async def update_sync_run_stats(
    session: AsyncSession,
    run_id: str,
    files_added: int = 0,
    files_modified: int = 0,
    files_deleted: int = 0,
    files_unchanged: int = 0,
    bytes_transferred: int = 0,
) -> None:
    """Update running counts on an active sync run."""
    stmt = (
        update(SyncRun)
        .where(SyncRun.run_id == run_id)
        .values(
            files_added=files_added,
            files_modified=files_modified,
            files_deleted=files_deleted,
            files_unchanged=files_unchanged,
            bytes_transferred=bytes_transferred,
        )
    )
    await session.execute(stmt)
    await session.commit()

async def finish_sync_run(
    session: AsyncSession,
    run_id: str,
    status: str,
    error_log: Optional[str] = None,
    files_added: Optional[int] = None,
    files_modified: Optional[int] = None,
    files_deleted: Optional[int] = None,
    files_unchanged: Optional[int] = None,
    bytes_transferred: Optional[int] = None,
) -> Optional[SyncRun]:
    """Finalize a sync run with completion status, timing, and error log."""
    values: Dict[str, Any] = {
        "status": status,
        "finished_at": datetime.now(timezone.utc),
    }
    if error_log is not None:
        values["error_log"] = error_log
    if files_added is not None:
        values["files_added"] = files_added
    if files_modified is not None:
        values["files_modified"] = files_modified
    if files_deleted is not None:
        values["files_deleted"] = files_deleted
    if files_unchanged is not None:
        values["files_unchanged"] = files_unchanged
    if bytes_transferred is not None:
        values["bytes_transferred"] = bytes_transferred

    stmt = update(SyncRun).where(SyncRun.run_id == run_id).values(**values)
    await session.execute(stmt)
    await session.commit()
    return await get_sync_run(session, run_id)

async def add_file_changes_batch(
    session: AsyncSession,
    run_id: str,
    changes: List[Dict[str, Any]],
) -> None:
    """Bulk insert file change records."""
    if not changes:
        return
    objects = [
        FileChange(
            run_id=run_id,
            action=item.get("action", "modified"),
            file_path=item.get("file_path", ""),
            file_size=item.get("file_size"),
            source_mtime=item.get("source_mtime"),
            error=item.get("error"),
        )
        for item in changes
    ]
    session.add_all(objects)
    await session.commit()

async def get_sync_run(session: AsyncSession, run_id: str) -> Optional[SyncRun]:
    """Get single sync run by its UUID."""
    stmt = select(SyncRun).where(SyncRun.run_id == run_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()

async def get_sync_runs(
    session: AsyncSession,
    pair_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[SyncRun], int]:
    """Get paginated sync runs with optional filters."""
    query = select(SyncRun)
    count_query = select(func.count(SyncRun.run_id))

    if pair_id:
        query = query.where(SyncRun.sync_pair_id == pair_id)
        count_query = count_query.where(SyncRun.sync_pair_id == pair_id)
    if status:
        query = query.where(SyncRun.status == status)
        count_query = count_query.where(SyncRun.status == status)

    query = query.order_by(desc(SyncRun.started_at)).limit(limit).offset(offset)

    total = (await session.execute(count_query)).scalar_one()
    results = (await session.execute(query)).scalars().all()
    return list(results), total

async def get_file_changes(
    session: AsyncSession,
    run_id: str,
    action: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Tuple[List[FileChange], int]:
    """Get paginated file changes for a specific run."""
    query = select(FileChange).where(FileChange.run_id == run_id)
    count_query = select(func.count(FileChange.change_id)).where(FileChange.run_id == run_id)

    if action and action != "all":
        query = query.where(FileChange.action == action)
        count_query = count_query.where(FileChange.action == action)

    if search:
        pattern = f"%{search}%"
        query = query.where(FileChange.file_path.ilike(pattern))
        count_query = count_query.where(FileChange.file_path.ilike(pattern))

    query = query.order_by(FileChange.change_id).limit(limit).offset(offset)

    total = (await session.execute(count_query)).scalar_one()
    results = (await session.execute(query)).scalars().all()
    return list(results), total

async def get_dashboard_stats(session: AsyncSession) -> Dict[str, Any]:
    """Compute overall dashboard statistics."""
    total_runs_q = select(func.count(SyncRun.run_id))
    completed_runs_q = select(func.count(SyncRun.run_id)).where(SyncRun.status == "completed")
    failed_runs_q = select(func.count(SyncRun.run_id)).where(SyncRun.status == "failed")
    total_bytes_q = select(func.sum(SyncRun.bytes_transferred))

    total_runs = (await session.execute(total_runs_q)).scalar_one() or 0
    completed_runs = (await session.execute(completed_runs_q)).scalar_one() or 0
    failed_runs = (await session.execute(failed_runs_q)).scalar_one() or 0
    total_bytes = (await session.execute(total_bytes_q)).scalar_one() or 0

    recent_runs_q = select(SyncRun).order_by(desc(SyncRun.started_at)).limit(5)
    recent_runs = (await session.execute(recent_runs_q)).scalars().all()

    return {
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "failed_runs": failed_runs,
        "total_bytes_transferred": total_bytes,
        "recent_runs": list(recent_runs),
    }

async def delete_sync_run(session: AsyncSession, run_id: str) -> bool:
    """Delete a sync run and its cascade file changes."""
    stmt = delete(SyncRun).where(SyncRun.run_id == run_id)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount > 0
