import os
import re
from pathlib import Path
from typing import List, Optional, Literal
import yaml
from pydantic import BaseModel, Field

CONFIG_FILE_ENV = "SYNCTOHDD_CONFIG"
DEFAULT_CONFIG_PATH = Path("config.yaml")

class SyncPairConfig(BaseModel):
    id: str = Field(default="", description="Unique identifier for the sync pair")
    name: str = Field(..., description="Human-readable name")
    source: str = Field(..., description="Source directory path")
    destination: str = Field(..., description="Destination directory path")
    mode: Literal["mirror", "additive"] = Field(
        default="mirror",
        description="'mirror' deletes dest files missing in source; 'additive' keeps them",
    )
    exclude: List[str] = Field(default_factory=list, description="Glob patterns to exclude")
    checksum: bool = Field(default=False, description="Compare by SHA-256 hash instead of mtime/size")
    bandwidth_limit: Optional[str] = Field(default=None, description="Optional bandwidth rate limit e.g. 50M")

    def ensure_id(self) -> str:
        if not self.id:
            slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", self.name.lower()).strip("-")
            self.id = slug or "sync-pair"
        return self.id

class ServerConfig(BaseModel):
    host: str = Field(default="0.0.0.0", description="Bind host")
    port: int = Field(default=6060, description="Web server port")
    log_level: str = Field(default="info", description="Logging level")

class DatabaseConfig(BaseModel):
    path: str = Field(default="./data/synctohdd.db", description="Path to SQLite database")

class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    sync_pairs: List[SyncPairConfig] = Field(default_factory=list)

    def get_pair_by_id(self, pair_id: str) -> Optional[SyncPairConfig]:
        for pair in self.sync_pairs:
            if pair.id == pair_id or pair.name == pair_id:
                return pair
        return None

def get_config_path(override_path: Optional[str] = None) -> Path:
    if override_path:
        p = Path(override_path).resolve()
        if p.is_dir():
            return (p / "config.yaml").resolve()
        return p

    env_path = os.getenv(CONFIG_FILE_ENV)
    if env_path:
        p = Path(env_path).resolve()
        if p.is_dir():
            return (p / "config.yaml").resolve()
        return p

    data_config = Path("data/config.yaml")
    if data_config.is_file():
        return data_config.resolve()
    elif data_config.is_dir():
        return (data_config / "config.yaml").resolve()

    return DEFAULT_CONFIG_PATH.resolve()

def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load configuration from YAML file or return defaults."""
    target_path = get_config_path(config_path)
    if not target_path.is_file():
        source_template = None
        for candidate in [
            Path("config.yaml"),
            Path("config.yaml.example"),
            target_path.with_name("config.yaml.example"),
            Path("/app/config.yaml.example"),
            Path("/app/config.yaml"),
        ]:
            if candidate.exists() and candidate.is_file() and candidate.resolve() != target_path.resolve():
                source_template = candidate
                break

        if source_template:
            with open(source_template, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                cfg = AppConfig(**data)
                for pair in cfg.sync_pairs:
                    pair.ensure_id()
                try:
                    save_config(cfg, str(target_path))
                except Exception:
                    pass
                return cfg
        return AppConfig()

    with open(target_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    config = AppConfig(**data)
    for pair in config.sync_pairs:
        pair.ensure_id()
    return config

def save_config(config: AppConfig, config_path: Optional[str] = None) -> None:
    """Persist current configuration to YAML file."""
    target_path = get_config_path(config_path)
    if target_path.is_dir():
        target_path = target_path / "config.yaml"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    dict_data = config.model_dump()
    with open(target_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(dict_data, f, sort_keys=False, default_flow_style=False)
