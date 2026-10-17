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
        return Path(override_path).resolve()
    env_path = os.getenv(CONFIG_FILE_ENV)
    if env_path:
        return Path(env_path).resolve()
    return DEFAULT_CONFIG_PATH.resolve()

def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load configuration from YAML file or return defaults."""
    target_path = get_config_path(config_path)
    if not target_path.exists():
        example_path = target_path.with_name("config.yaml.example")
        if example_path.exists():
            with open(example_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                cfg = AppConfig(**data)
                for pair in cfg.sync_pairs:
                    pair.ensure_id()
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
    target_path.parent.mkdir(parents=True, exist_ok=True)
    dict_data = config.model_dump()
    with open(target_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(dict_data, f, sort_keys=False, default_flow_style=False)
