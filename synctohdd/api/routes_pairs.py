from fastapi import APIRouter, HTTPException, status
from typing import List, Dict, Any
from synctohdd.config import SyncPairConfig, load_config, save_config
from synctohdd.utils.platform import check_path_status, get_disk_usage

router = APIRouter(prefix="/api/pairs", tags=["Sync Pairs"])

@router.get("", response_model=List[SyncPairConfig])
def list_sync_pairs():
    """Retrieve all configured sync pairs."""
    config = load_config()
    return config.sync_pairs

@router.post("", response_model=SyncPairConfig, status_code=status.HTTP_201_CREATED)
def create_sync_pair(pair: SyncPairConfig):
    """Add a new sync pair to configuration."""
    config = load_config()
    pair.ensure_id()

    # Check for duplicate ID
    if any(p.id == pair.id for p in config.sync_pairs):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A sync pair with ID '{pair.id}' already exists",
        )

    config.sync_pairs.append(pair)
    save_config(config)
    return pair

@router.get("/{pair_id}", response_model=SyncPairConfig)
def get_sync_pair(pair_id: str):
    """Retrieve a single sync pair by ID."""
    config = load_config()
    pair = config.get_pair_by_id(pair_id)
    if not pair:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync pair not found")
    return pair

@router.put("/{pair_id}", response_model=SyncPairConfig)
def update_sync_pair(pair_id: str, updated: SyncPairConfig):
    """Update an existing sync pair."""
    config = load_config()
    target_idx = None
    for i, p in enumerate(config.sync_pairs):
        if p.id == pair_id or p.name == pair_id:
            target_idx = i
            break

    if target_idx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync pair not found")

    updated.id = pair_id  # maintain ID
    config.sync_pairs[target_idx] = updated
    save_config(config)
    return updated

@router.delete("/{pair_id}")
def delete_sync_pair(pair_id: str):
    """Delete a sync pair from configuration."""
    config = load_config()
    initial_len = len(config.sync_pairs)
    config.sync_pairs = [p for p in config.sync_pairs if p.id != pair_id and p.name != pair_id]

    if len(config.sync_pairs) == initial_len:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync pair not found")

    save_config(config)
    return {"message": f"Sync pair '{pair_id}' deleted successfully"}

@router.post("/{pair_id}/duplicate", response_model=SyncPairConfig, status_code=status.HTTP_201_CREATED)
def duplicate_sync_pair(pair_id: str):
    """Duplicate an existing sync pair with a new unique ID and name."""
    config = load_config()
    new_pair = config.duplicate_pair(pair_id)
    if not new_pair:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync pair not found")
    save_config(config)
    return new_pair

@router.post("/{pair_id}/test", response_model=Dict[str, Any])
def test_sync_pair_paths(pair_id: str):
    """Test accessibility, readability, and disk space for a pair's source and destination."""
    config = load_config()
    pair = config.get_pair_by_id(pair_id)
    if not pair:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync pair not found")

    src_status = check_path_status(pair.source, check_write=False)
    dst_status = check_path_status(pair.destination, check_write=True)
    dst_disk = get_disk_usage(pair.destination)

    return {
        "pair_id": pair.id,
        "pair_name": pair.name,
        "source": src_status,
        "destination": dst_status,
        "destination_disk": dst_disk,
    }
