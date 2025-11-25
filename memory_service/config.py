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

# Database base path (per-source databases will be in subfolders)
BASE_STORE_PATH = BASE_DIR / "memory_service" / "store"

# Global tracking database for dashboard (tracks all sources)
TRACKING_DB_PATH = BASE_STORE_PATH / "tracking.sqlite"

def get_db_path_for_source(source_id: str) -> Path:
    """Get the database path for a specific source."""
    source_dir = BASE_STORE_PATH / source_id
    source_dir.mkdir(parents=True, exist_ok=True)
    return source_dir / "index.sqlite"

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
    """
    Load source configurations from memory_sources.yaml.
    Auto-detects project_id from projects.json if source is connected via UI.
    """
    ensure_config_dir()
    
    if not MEMORY_SOURCES_YAML.exists():
        return []
    
    with open(MEMORY_SOURCES_YAML, 'r') as f:
        config = yaml.safe_load(f)
    
    # Load projects to auto-detect project_id from connections
    projects_map = {}
    try:
        projects_path = BASE_DIR / "server" / "data" / "projects.json"
        if projects_path.exists():
            import json
            with open(projects_path, 'r') as pf:
                projects = json.load(pf)
                for project in projects:
                    for source_id in project.get("memory_sources", []):
                        projects_map[source_id] = project["id"]
    except Exception as e:
        # If we can't load projects, continue with YAML project_id
        pass
    
    sources = []
    for source_data in config.get("sources", []):
        source_id = source_data.get("id")
        
        # Auto-detect project_id from projects.json if source is connected
        if source_id in projects_map:
            source_data["project_id"] = projects_map[source_id]
        
        sources.append(SourceConfig(source_data))
    
    return sources


def ensure_config_dir():
    """Ensure the config directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def sync_yaml_from_projects():
    """
    Sync project_id in memory_sources.yaml from projects.json connections.
    This ensures the YAML stays in sync when sources are connected/disconnected via UI.
    """
    ensure_config_dir()
    
    if not MEMORY_SOURCES_YAML.exists():
        return
    
    # Load current YAML
    with open(MEMORY_SOURCES_YAML, 'r') as f:
        config = yaml.safe_load(f) or {}
    
    # Build map of source_id -> project_id from projects.json
    projects_map = {}
    try:
        projects_path = BASE_DIR / "server" / "data" / "projects.json"
        if projects_path.exists():
            import json
            with open(projects_path, 'r') as pf:
                projects = json.load(pf)
                for project in projects:
                    for source_id in project.get("memory_sources", []):
                        projects_map[source_id] = project["id"]
    except Exception as e:
        # If we can't load projects, skip sync
        return
    
    # Update project_id for each source in YAML if it's connected
    updated = False
    sources = config.get("sources", [])
    for source in sources:
        source_id = source.get("id")
        if source_id in projects_map:
            # Source is connected to a project - update project_id
            new_project_id = projects_map[source_id]
            if source.get("project_id") != new_project_id:
                source["project_id"] = new_project_id
                updated = True
    
    # Save YAML if updated
    if updated:
        with open(MEMORY_SOURCES_YAML, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

