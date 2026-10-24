import argparse
import asyncio
import sys
import uvicorn
from pathlib import Path

from synctohdd.config import load_config
from synctohdd.db.database import init_db
from synctohdd.db import crud
from synctohdd.engine.manager import sync_manager
from synctohdd.utils.logger import logger, setup_logger


def run_server(host: str, port: int, log_level: str = "info"):
    """Launch the FastAPI uvicorn web server."""
    logger.info(f"Starting SyncToHDD Web Server on http://{host}:{port}")
    uvicorn.run(
        "synctohdd.api.app:app",
        host=host,
        port=port,
        log_level=log_level.lower(),
        reload=False,
    )

async def run_cli_sync(pair_target: str, dry_run: bool):
    """Execute a sync job directly from CLI without starting the web server."""
    config = load_config()
    await init_db(config.database.path)

    if pair_target.lower() == "all":
        logger.info(f"Starting CLI sync for ALL configured pairs (dry_run={dry_run})...")
        for pair in config.sync_pairs:
            logger.info(f"=== Starting Sync: {pair.name} ({pair.source} -> {pair.destination}) ===")
            run_id = await sync_manager.start_sync_job(pair, dry_run=dry_run)
            while sync_manager.is_running and sync_manager.active_run_id == run_id:
                await asyncio.sleep(0.5)
        logger.info("All CLI sync jobs completed.")
    else:
        pair = config.get_pair_by_id(pair_target)
        if not pair:
            logger.error(f"Sync pair '{pair_target}' not found in configuration.")
            sys.exit(1)

        logger.info(f"Starting CLI sync for '{pair.name}' (dry_run={dry_run})...")
        run_id = await sync_manager.start_sync_job(pair, dry_run=dry_run)
        while sync_manager.is_running and sync_manager.active_run_id == run_id:
            await asyncio.sleep(0.5)
        logger.info(f"CLI sync for '{pair.name}' finished.")

def list_pairs_cli():
    """Print configured sync pairs."""
    config = load_config()
    print("\nConfigured Sync Pairs:")
    print("-" * 70)
    for p in config.sync_pairs:
        print(f"ID:          {p.id}")
        print(f"Name:        {p.name}")
        print(f"Source:      {p.source}")
        print(f"Destination: {p.destination}")
        print(f"Mode:        {p.mode}")
        print(f"Checksum:    {p.checksum}")
        print(f"Exclusions:  {', '.join(p.exclude) if p.exclude else 'None'}")
        print("-" * 70)

def main():
    parser = argparse.ArgumentParser(description="SyncToHDD — File Sync & Backup Tool")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Server command
    server_parser = subparsers.add_parser("server", help="Start the Web UI & API server (default)")
    server_parser.add_argument("--host", default=None, help="Host to bind (default from config or 0.0.0.0)")
    server_parser.add_argument("--port", type=int, default=None, help="Port to bind (default from config or 6060)")

    # Sync command
    sync_parser = subparsers.add_parser("sync", help="Run sync directly from CLI")
    sync_parser.add_argument("pair", help="Sync pair ID or 'all'")
    sync_parser.add_argument("--dry-run", action="store_true", help="Preview changes without modifying destination")

    # List command
    subparsers.add_parser("list", help="List configured sync pairs")

    # Init-db command
    subparsers.add_parser("init-db", help="Initialize database schema")

    # Clear-history command
    clear_parser = subparsers.add_parser("clear-history", help="Clear sync run history")
    clear_parser.add_argument("-y", "--yes", action="store_true", help="Confirm deletion without interactive prompt")
    clear_parser.add_argument("--pair", default=None, help="Optional sync pair ID to clear")
    clear_parser.add_argument("--status", default=None, help="Optional status to clear (e.g. completed, failed)")
    clear_parser.add_argument("--include-running", action="store_true", help="Also clear currently running sync runs")

    args = parser.parse_args()

    # Default action if no subcommand passed: start server
    if args.command is None or args.command == "server":
        config = load_config()
        host = getattr(args, "host", None) or config.server.host
        port = getattr(args, "port", None) or config.server.port
        log_level = config.server.log_level
        run_server(host, port, log_level)
    elif args.command == "sync":
        asyncio.run(run_cli_sync(args.pair, args.dry_run))
    elif args.command == "list":
        list_pairs_cli()
    elif args.command == "init-db":
        config = load_config()
        asyncio.run(init_db(config.database.path))
        print("Database initialized successfully.")
    elif args.command == "clear-history":
        if not args.yes:
            prompt_target = f"for pair '{args.pair}'" if args.pair else "ALL"
            confirm = input(f"Are you sure you want to clear {prompt_target} sync run history? (y/N): ")
            if confirm.strip().lower() not in ("y", "yes"):
                print("Aborted.")
                sys.exit(0)
        config = load_config()

        async def do_clear():
            await init_db(config.database.path)
            from synctohdd.db.database import get_session_factory
            factory = get_session_factory(config.database.path)
            async with factory() as session:
                count = await crud.clear_all_sync_runs(
                    session=session,
                    keep_running=not args.include_running,
                    pair_id=args.pair,
                    status=args.status,
                )
                print(f"Successfully cleared {count} sync run record(s).")

        asyncio.run(do_clear())


if __name__ == "__main__":
    main()
