"""
Configuration management for Memory Service.

Loads source configurations from YAML and provides access to service settings.
"""
import yaml
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
import os
import tempfile
import shutil

# Base directory for ChatDO
BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
MEMORY_SOURCES_YAML = CONFIG_DIR / "memory_sources.yaml"

# Memory Dashboard path (for indexed file sources only)
MEMORY_DASHBOARD_PATH = BASE_DIR / "memory_service" / "memory_dashboard"

# Projects path (for project chat threads and indexes)
PROJECTS_PATH = BASE_DIR / "memory_service" / "projects"

# Global tracking database for dashboard (tracks all sources)
TRACKING_DB_PATH = MEMORY_DASHBOARD_PATH / "tracking.sqlite"

# Dynamic sources JSON file (for UI-created sources)
DYNAMIC_SOURCES_PATH = MEMORY_DASHBOARD_PATH / "dynamic_sources.json"

# Legacy alias for backward compatibility (will be removed)
BASE_STORE_PATH = MEMORY_DASHBOARD_PATH

def get_project_directory_name(project_id: str) -> str:
    """
    Get the directory name for a project in memory_service/projects/.
    
    Uses slugified project name from projects.json, or project_id as fallback.
    This ensures each project has its own directory, separate from default_target.
    
    Args:
        project_id: The project ID to look up
        
    Returns:
        Directory name to use in projects/ folder (slugified name or project_id)
    """
    try:
        projects_path = BASE_DIR / "server" / "data" / "projects.json"
        if projects_path.exists():
            with open(projects_path, 'r') as f:
                projects = json.load(f)
                for project in projects:
                    if project.get("id") == project_id:
                        # Use slugified project name for directory
                        project_name = project.get("name", "")
                        if project_name:
                            return slugify(project_name)
                        # Fallback to project_id if no name
                        return project_id
    except Exception:
        pass
    
    # Fallback to project_id
    return project_id


def get_db_path_for_source(source_id: str, project_id: Optional[str] = None) -> Path:
    """
    Get the database path for a specific source.
    
    For project chat message indexes (source_id starts with "project-"):
    - Stores in projects/<project_directory_name>/index/index.sqlite
      where project_directory_name is slugified project name from projects.json
    
    For file source indexes (all other source_ids):
    - Stores in memory_dashboard/<source_id>/index.sqlite
    
    Args:
        source_id: Source ID (e.g., "project-{project_id}" for chat indexes, or "coin-dir" for file sources)
        project_id: Optional project_id (used to look up project directory name for project indexes)
    """
    if source_id.startswith("project-"):
        # This is a project chat message index
        # Extract project_id from source_id (format: "project-<project_id>")
        actual_project_id = source_id.replace("project-", "")
        
        # Use passed project_id if available, otherwise use extracted one
        lookup_project_id = project_id if project_id else actual_project_id
        
        # Get project directory name (slugified project name, not default_target)
        project_dir_name = get_project_directory_name(lookup_project_id)
        
        # Store in projects/<project_dir_name>/index/index.sqlite
        index_dir = PROJECTS_PATH / project_dir_name / "index"
        index_dir.mkdir(parents=True, exist_ok=True)
        return index_dir / "index.sqlite"
    else:
        # This is a file source index - store in memory_dashboard
        source_dir = MEMORY_DASHBOARD_PATH / source_id
        source_dir.mkdir(parents=True, exist_ok=True)
        return source_dir / "index.sqlite"

# Embedding model
EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
EMBEDDING_DIM = 1024

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
        self.display_name = data.get("display_name", self.id)
    
    def __repr__(self):
        return f"SourceConfig(id={self.id}, project_id={self.project_id}, root_path={self.root_path})"


def get_default_exclude_glob() -> str:
    """Get default exclude patterns for new sources."""
    return "**/.git/**,**/node_modules/**,**/dist/**,**/build/**,**/.next/**,**/.turbo/**,**/.cache/**,**/.venv/**,**/venv/**,**/*.sqlite,**/*.sqlite-journal,**/*-wal"


def load_static_sources() -> List[SourceConfig]:
    """Load static sources from memory_sources.yaml."""
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


def load_dynamic_sources() -> List[SourceConfig]:
    """Load dynamic sources from JSON file."""
    if not DYNAMIC_SOURCES_PATH.exists():
        return []
    
    try:
        with open(DYNAMIC_SOURCES_PATH, 'r') as f:
            sources_data = json.load(f)
        
        # Load projects to auto-detect project_id from connections (same as static sources)
        projects_map = {}
        try:
            projects_path = BASE_DIR / "server" / "data" / "projects.json"
            if projects_path.exists():
                with open(projects_path, 'r') as pf:
                    projects = json.load(pf)
                    for project in projects:
                        for source_id in project.get("memory_sources", []):
                            projects_map[source_id] = project["id"]
        except Exception as e:
            # If we can't load projects, continue with JSON project_id
            pass
        
        # Update project_id from projects.json if source is connected
        for source_data in sources_data:
            source_id = source_data.get("id")
            if source_id in projects_map:
                source_data["project_id"] = projects_map[source_id]
        
        return [SourceConfig(source_data) for source_data in sources_data]
    except Exception as e:
        # If file is corrupted, return empty list
        return []


def save_dynamic_sources(sources: List[SourceConfig]) -> None:
    """Save dynamic sources to JSON file atomically."""
    MEMORY_DASHBOARD_PATH.mkdir(parents=True, exist_ok=True)
    
    # Convert to dicts
    sources_data = [
        {
            "id": src.id,
            "project_id": src.project_id,
            "root_path": str(src.root_path),
            "include_glob": src.include_glob,
            "exclude_glob": src.exclude_glob,
            "display_name": src.display_name,
        }
        for src in sources
    ]
    
    # Atomic write
    with tempfile.NamedTemporaryFile(mode='w', dir=MEMORY_DASHBOARD_PATH, delete=False, suffix='.json') as f:
        json.dump(sources_data, f, indent=2)
        temp_path = Path(f.name)
    
    # Rename atomically
    shutil.move(str(temp_path), str(DYNAMIC_SOURCES_PATH))


def merge_static_and_dynamic(static_sources: List[SourceConfig],
                             dynamic_sources: List[SourceConfig]) -> List[SourceConfig]:
    """Merge static and dynamic sources, avoiding duplicate source_ids."""
    seen_ids = set()
    merged = []
    
    # Add static sources first
    for src in static_sources:
        if src.id not in seen_ids:
            merged.append(src)
            seen_ids.add(src.id)
    
    # Add dynamic sources (skip if ID already exists)
    for src in dynamic_sources:
        if src.id not in seen_ids:
            merged.append(src)
            seen_ids.add(src.id)
    
    return merged


def load_sources() -> List[SourceConfig]:
    """
    Load source configurations from memory_sources.yaml and dynamic_sources.json.
    Auto-detects project_id from projects.json if source is connected via UI.
    """
    static = load_static_sources()
    dynamic = load_dynamic_sources()
    return merge_static_and_dynamic(static, dynamic)


def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    # Convert to lowercase and replace spaces/special chars with hyphens
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


def create_dynamic_source(root_path: str,
                          display_name: Optional[str] = None,
                          project_id: str = "general") -> SourceConfig:
    """
    Create a new SourceConfig for a dynamically added folder, persist it, and return it.
    
    - display_name defaults to basename of root_path (without trailing slash)
    - source_id = slugified(display_name) + "-dir"
      * if already taken, append "-2", "-3", etc.
    - include/exclude globs use default patterns
    """
    # Validate path
    path = Path(root_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Path does not exist: {root_path}")
    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {root_path}")
    
    # Determine display name
    if not display_name:
        display_name = path.name or path.stem or "untitled"
    
    # Generate source_id
    base_id = slugify(display_name) + "-dir"
    source_id = base_id
    
    # Check for existing sources (static + dynamic) to avoid duplicates
    existing_sources = load_sources()
    existing_ids = {src.id for src in existing_sources}
    
    counter = 2
    while source_id in existing_ids:
        source_id = f"{base_id}-{counter}"
        counter += 1
    
    # Create source config
    source_data = {
        "id": source_id,
        "project_id": project_id,
        "root_path": str(path),
        "include_glob": "**/*",
        "exclude_glob": get_default_exclude_glob(),
        "display_name": display_name,
    }
    
    source_config = SourceConfig(source_data)
    
    # Persist to dynamic sources JSON
    dynamic_sources = load_dynamic_sources()
    dynamic_sources.append(source_config)
    save_dynamic_sources(dynamic_sources)
    
    return source_config


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

