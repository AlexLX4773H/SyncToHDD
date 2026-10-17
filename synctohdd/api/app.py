from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from synctohdd.config import load_config
from synctohdd.db.database import init_db
from synctohdd.api.routes_pairs import router as pairs_router
from synctohdd.api.routes_sync import router as sync_router
from synctohdd.api.routes_runs import router as runs_router
from synctohdd.api.routes_events import router as events_router
from synctohdd.api.routes_system import router as system_router
from synctohdd.web.routes import router as web_router
from synctohdd.utils.logger import logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager to initialize database and resources on startup."""
    config = load_config()
    db_path = config.database.path
    logger.info(f"Starting SyncToHDD application. Initializing database at {db_path}...")
    await init_db(db_path)
    logger.info("Database ready. Server started.")
    yield
    logger.info("SyncToHDD shutting down.")

def create_app() -> FastAPI:
    """FastAPI application factory."""
    app = FastAPI(
        title="SyncToHDD",
        description="Self-hosted file & directory synchronization tool with Web UI and run history",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static assets
    static_dir = Path(__file__).parent.parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # API Routes
    app.include_router(pairs_router)
    app.include_router(sync_router)
    app.include_router(runs_router)
    app.include_router(events_router)
    app.include_router(system_router)

    # Web UI Routes
    app.include_router(web_router)

    @app.get("/api/health", tags=["Health"])
    def health_check():
        return {"status": "ok", "app": "SyncToHDD", "version": "0.1.0"}

    return app

app = create_app()
