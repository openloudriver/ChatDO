"""
Configuration management for Memory Service.

Loads source configurations from YAML and provides access to service settings.
"""
import yaml
from pathlib import Path
from typing import List, Dict, Any
import os

# Base directory for ChatDO
BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
MEMORY_SOURCES_YAML = CONFIG_DIR / "memory_sources.yaml"

# Database path
DB_PATH = BASE_DIR / "memory_service" / "store" / "index.sqlite"

# Embedding model
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

# Chunking settings
CHUNK_SIZE_CHARS = 2500  # Target chunk size in characters
CHUNK_OVERLAP_CHARS = 200  # Overlap between chunks

# API settings
API_HOST = "127.0.0.1"
API_PORT = 5858


class SourceConfig:
    """Represents a single source configuration."""
    def __init__(self, data: Dict[str, Any]):
        self.id = data["id"]
        self.project_id = data["project_id"]
        self.root_path = Path(data["root_path"]).expanduser().resolve()
        self.include_glob = data.get("include_glob", "**/*")
        self.exclude_glob = data.get("exclude_glob", "")
    
    def __repr__(self):
        return f"SourceConfig(id={self.id}, project_id={self.project_id}, root_path={self.root_path})"


def load_sources() -> List[SourceConfig]:
    """Load source configurations from memory_sources.yaml."""
    ensure_config_dir()
    
    if not MEMORY_SOURCES_YAML.exists():
        return []
    
    with open(MEMORY_SOURCES_YAML, 'r') as f:
        config = yaml.safe_load(f)
    
    sources = []
    for source_data in config.get("sources", []):
        sources.append(SourceConfig(source_data))
    
    return sources


def ensure_config_dir():
    """Ensure the config directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

