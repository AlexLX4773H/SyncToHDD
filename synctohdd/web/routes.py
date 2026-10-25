import math
from pathlib import Path
from datetime import datetime, timezone
import humanize
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, HTTPException

from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from synctohdd.config import load_config, save_config, SyncPairConfig, generate_duplicate_name, sort_sync_pairs
from synctohdd.db.database import get_db
from synctohdd.db import crud
from synctohdd.engine.manager import sync_manager
from synctohdd.utils.platform import is_linux, has_rsync, get_disk_usage

router = APIRouter(include_in_schema=False)

templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))
static_dir = Path(__file__).parent / "static"

@router.get("/favicon.ico", include_in_schema=False)
async def favicon_route():
    """Serve favicon.ico directly at the root URL."""
    fav_path = static_dir / "favicon.ico"
    if fav_path.exists():
        return FileResponse(str(fav_path), media_type="image/x-icon")
    icon_path = static_dir / "icon.png"
    return FileResponse(str(icon_path), media_type="image/png")

def format_bytes(b: int) -> str:
    """Format bytes into readable string."""
    if not b:
        return "0 B"
    return humanize.naturalsize(b, binary=True)

def format_duration(start: datetime, end: datetime) -> str:
    """Calculate and format run duration in seconds / minutes."""
    if not start or not end:
        return "-"
    seconds = int((end - start).total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    rem_secs = seconds % 60
    return f"{minutes}m {rem_secs}s"

templates.env.filters["format_bytes"] = format_bytes
templates.env.filters["format_duration"] = format_duration

@router.get("/", response_class=HTMLResponse)
async def dashboard_view(request: Request, db: AsyncSession = Depends(get_db)):
    """Render main dashboard with summary statistics and quick action cards."""
    config = load_config()
    stats = await crud.get_dashboard_stats(db)

    # Get disk space for destination drives of configured pairs (1 pill per unique drive)
    disks = {}
    for pair in config.sync_pairs:
        d = get_disk_usage(pair.destination)
        if not d:
            continue

        # Match existing drive to ensure only 1 pill per physical/logical drive
        match_key = None
        for key, existing_d in disks.items():
            # 1. Match by device_id (Linux st_dev or Windows drive ID)
            if d.get("device_id") and d.get("device_id") == existing_d.get("device_id"):
                match_key = key
                break
            # 2. Match by normalized mount path
            if d.get("mount_path") and existing_d.get("mount_path"):
                p1 = str(d["mount_path"]).replace("\\", "/").rstrip("/").lower()
                p2 = str(existing_d["mount_path"]).replace("\\", "/").rstrip("/").lower()
                if p1 == p2:
                    match_key = key
                    break
            # 3. Match by identical capacity and friendly drive name
            if (
                d.get("total_bytes")
                and d.get("total_bytes") == existing_d.get("total_bytes")
                and d.get("drive_name")
                and d.get("drive_name") == existing_d.get("drive_name")
            ):
                match_key = key
                break

        if match_key:
            disks[match_key]["pairs_count"] += 1
            if pair.name not in disks[match_key]["pairs"]:
                disks[match_key]["pairs"].append(pair.name)
        else:
            drive_key = d.get("device_id") or str(d.get("mount_path")) or str(len(disks))
            d["pairs_count"] = 1
            d["pairs"] = [pair.name]
            disks[drive_key] = d

    sorted_pairs = sort_sync_pairs(config.sync_pairs, sort_by="name", order="asc")

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "config": config,
            "pairs": sorted_pairs,
            "stats": stats,
            "disks": list(disks.values()),
            "sync_status": sync_manager.get_status(),
            "has_rsync": has_rsync(),
            "is_linux": is_linux(),
            "active_tab": "dashboard",
        },
    )

@router.get("/pairs", response_class=HTMLResponse)
async def pairs_view(
    request: Request,
    sort: str = "name",
    order: str = "asc",
):
    """Render sync pairs management view, ordered by name by default."""
    config = load_config()
    normalized_sort = sort.lower().strip() if sort else "name"
    normalized_order = "desc" if str(order).lower().strip() == "desc" else "asc"
    sorted_pairs = sort_sync_pairs(config.sync_pairs, sort_by=normalized_sort, order=normalized_order)

    return templates.TemplateResponse(
        request=request,
        name="pairs.html",
        context={
            "pairs": sorted_pairs,
            "sync_status": sync_manager.get_status(),
            "active_tab": "pairs",
            "current_sort": normalized_sort,
            "current_order": normalized_order,
        },
    )

@router.get("/pairs/new", response_class=HTMLResponse)
async def pair_new_view(request: Request):
    """Render form to add a new sync pair."""
    return templates.TemplateResponse(
        request=request,
        name="pair_form.html",
        context={
            "pair": None,
            "is_new": True,
            "active_tab": "pairs",
        },
    )

@router.get("/pairs/{pair_id}/edit", response_class=HTMLResponse)
async def pair_edit_view(pair_id: str, request: Request):
    """Render form to edit an existing sync pair."""
    config = load_config()
    pair = config.get_pair_by_id(pair_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Sync pair not found")

    return templates.TemplateResponse(
        request=request,
        name="pair_form.html",
        context={
            "pair": pair,
            "is_new": False,
            "active_tab": "pairs",
        },
    )

@router.get("/pairs/{pair_id}/duplicate", response_class=HTMLResponse)
async def pair_duplicate_view(pair_id: str, request: Request):
    """Render form to duplicate an existing sync pair."""
    config = load_config()
    pair = config.get_pair_by_id(pair_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Sync pair not found")

    existing_names = {p.name for p in config.sync_pairs}
    suggested_name = generate_duplicate_name(pair.name, existing_names)

    duplicate_pair = SyncPairConfig(
        id="",
        name=suggested_name,
        source=pair.source,
        destination=pair.destination,
        mode=pair.mode,
        exclude=list(pair.exclude),
        checksum=pair.checksum,
        bandwidth_limit=pair.bandwidth_limit,
    )

    return templates.TemplateResponse(
        request=request,
        name="pair_form.html",
        context={
            "pair": duplicate_pair,
            "original_pair": pair,
            "is_new": True,
            "is_duplicate": True,
            "active_tab": "pairs",
        },
    )

@router.post("/pairs/save")
async def pair_save_action(
    id: str = Form(""),
    name: str = Form(...),
    source: str = Form(...),
    destination: str = Form(...),
    mode: str = Form("mirror"),
    exclude_text: str = Form(""),
    checksum: bool = Form(False),
    bandwidth_limit: str = Form(""),
):
    """Handle creation or update of a sync pair."""
    config = load_config()

    # Parse exclusions from linebreaks
    excludes = [line.strip() for line in exclude_text.splitlines() if line.strip()]

    pair = SyncPairConfig(
        id=id.strip(),
        name=name.strip(),
        source=source.strip(),
        destination=destination.strip(),
        mode="mirror" if mode == "mirror" else "additive",
        exclude=excludes,
        checksum=bool(checksum),
        bandwidth_limit=bandwidth_limit.strip() or None,
    )
    pair.ensure_id(config.sync_pairs if not id.strip() else None)

    existing_idx = None
    if id.strip():
        for idx, p in enumerate(config.sync_pairs):
            if p.id == id.strip():
                existing_idx = idx
                break

    if existing_idx is not None:
        config.sync_pairs[existing_idx] = pair
    else:
        config.sync_pairs.append(pair)

    save_config(config)
    return RedirectResponse(url="/pairs", status_code=303)

@router.get("/active", response_class=HTMLResponse)
async def active_run_view(request: Request):
    """Render live sync monitor page."""
    config = load_config()
    return templates.TemplateResponse(
        request=request,
        name="active_run.html",
        context={
            "sync_status": sync_manager.get_status(),
            "pairs": config.sync_pairs,
            "active_tab": "active",
        },
    )

@router.get("/runs", response_class=HTMLResponse)
async def runs_history_view(
    request: Request,
    pair: str = "",
    status: str = "",
    page: int = 1,
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
):
    """Render paginated run history table with filters."""
    offset = (page - 1) * limit
    runs, total = await crud.get_sync_runs(
        session=db,
        pair_id=pair if pair else None,
        status=status if status else None,
        limit=limit,
        offset=offset,
    )
    total_pages = math.ceil(total / limit) if total > 0 else 1
    config = load_config()

    overall_total = total
    if pair or status:
        _, overall_total = await crud.get_sync_runs(session=db, limit=1)

    return templates.TemplateResponse(
        request=request,
        name="runs.html",
        context={
            "runs": runs,
            "total": total,
            "overall_total": overall_total,
            "page": page,
            "total_pages": total_pages,
            "selected_pair": pair,
            "selected_status": status,
            "pairs": config.sync_pairs,
            "active_tab": "runs",
        },
    )

@router.post("/runs/clear")
async def runs_clear_web(
    request: Request,
    pair: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Web action to clear sync run history via form submission."""
    await crud.clear_all_sync_runs(
        session=db,
        keep_running=True,
        pair_id=pair.strip() if pair and pair.strip() else None,
        status=status.strip() if status and status.strip() else None,
    )
    return RedirectResponse(url="/runs", status_code=303)


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail_view(
    run_id: str,
    request: Request,
    action: str = "all",
    search: str = "",
    page: int = 1,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Render detail page for a specific sync run including file changes."""
    run = await crud.get_sync_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    offset = (page - 1) * limit
    changes, total = await crud.get_file_changes(
        session=db,
        run_id=run_id,
        action=action if action != "all" else None,
        search=search if search else None,
        limit=limit,
        offset=offset,
    )
    total_pages = math.ceil(total / limit) if total > 0 else 1

    return templates.TemplateResponse(
        request=request,
        name="run_detail.html",
        context={
            "run": run,
            "changes": changes,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "selected_action": action,
            "search_query": search,
            "active_tab": "runs",
        },
    )
