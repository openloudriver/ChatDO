"""
Project configuration management.

Handles loading, saving, and updating project data including memory source mappings.
"""
import json
from pathlib import Path
from typing import List, Dict, Optional

def get_projects_path() -> Path:
    """Get the path to projects.json"""
    return Path(__file__).parent.parent / "data" / "projects.json"


def load_projects() -> List[Dict]:
    """Load projects from projects.json, ensuring all required fields exist"""
    projects_path = get_projects_path()
    if not projects_path.exists():
        return []
    
    with open(projects_path, "r") as f:
        projects = json.load(f)
    
    # Ensure all projects have required fields
    needs_save = False
    for i, project in enumerate(projects):
        if "sort_index" not in project:
            project["sort_index"] = i
            needs_save = True
        if "memory_sources" not in project:
            project["memory_sources"] = []
            needs_save = True
        if "trashed" not in project:
            project["trashed"] = False
            needs_save = True
        if "trashed_at" not in project:
            project["trashed_at"] = None
            needs_save = True
        if "archived" not in project:
            project["archived"] = False
            needs_save = True
        if "archived_at" not in project:
            project["archived_at"] = None
            needs_save = True
    
    # Sort by sort_index, then by name as tie-breaker
    projects.sort(key=lambda p: (p.get("sort_index", 0), p.get("name", "")))
    
    # Save if we added any missing fields
    if needs_save:
        save_projects(projects)
    
    return projects


def save_projects(projects: List[Dict]) -> None:
    """Save projects to projects.json"""
    projects_path = get_projects_path()
    projects_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Use atomic write with temp file
    temp_path = projects_path.with_suffix('.json.tmp')
    with open(temp_path, "w") as f:
        json.dump(projects, f, indent=2)
    temp_path.replace(projects_path)


def get_project(project_id: str) -> Optional[Dict]:
    """Get a project by ID"""
    projects = load_projects()
    return next((p for p in projects if p.get("id") == project_id), None)


def update_project_memory_sources(project_id: str, memory_sources: List[str]) -> Dict:
    """Update memory sources for a project"""
    projects = load_projects()
    
    # Find project by ID
    project_index = None
    for i, p in enumerate(projects):
        if p.get("id") == project_id:
            project_index = i
            break
    
    if project_index is None:
        raise ValueError(f"Project not found: {project_id}")
    
    # Update memory_sources
    projects[project_index]["memory_sources"] = memory_sources
    save_projects(projects)
    
    return projects[project_index]

