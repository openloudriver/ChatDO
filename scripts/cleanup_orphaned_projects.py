#!/usr/bin/env python3
"""
Clean up orphaned memory service projects that don't have corresponding UI projects.

This script:
1. Loads all projects from server/data/projects.json
2. Lists all directories in memory_service/projects/
3. Identifies orphaned projects (memory service projects without UI projects)
4. Optionally deletes orphaned projects
"""
import json
import shutil
from pathlib import Path
from typing import Set, List, Tuple

# Paths
BASE_DIR = Path(__file__).parent.parent
PROJECTS_JSON = BASE_DIR / "server" / "data" / "projects.json"
MEMORY_PROJECTS_DIR = BASE_DIR / "memory_service" / "projects"


def get_project_directory_name(project: dict) -> str:
    """
    Get the directory name for a project in memory_service/projects/.
    
    This matches the logic in memory_service/config.py:get_project_directory_name()
    """
    # Try to use the project name (slugified)
    name = project.get("name", "")
    if name:
        # Slugify: lowercase, replace spaces with hyphens, remove special chars
        import re
        slug = re.sub(r'[^\w\s-]', '', name.lower())
        slug = re.sub(r'[-\s]+', '-', slug)
        slug = slug.strip('-')
        if slug:
            return slug
    
    # Fallback to project_id
    return project.get("id", "")


def load_ui_projects() -> List[dict]:
    """Load projects from projects.json"""
    if not PROJECTS_JSON.exists():
        print(f"⚠️  {PROJECTS_JSON} not found")
        return []
    
    with open(PROJECTS_JSON, "r") as f:
        projects = json.load(f)
    
    # Filter out trashed projects
    active_projects = [p for p in projects if not p.get("trashed", False)]
    return active_projects


def get_expected_project_dirs(projects: List[dict]) -> Set[str]:
    """Get the set of expected project directory names from UI projects"""
    expected_dirs = set()
    for project in projects:
        dir_name = get_project_directory_name(project)
        if dir_name:
            expected_dirs.add(dir_name)
    return expected_dirs


def find_orphaned_projects() -> List[Tuple[str, Path]]:
    """Find orphaned memory service projects"""
    ui_projects = load_ui_projects()
    expected_dirs = get_expected_project_dirs(ui_projects)
    
    print(f"📋 Found {len(ui_projects)} active UI projects")
    print(f"📁 Expected memory service directories: {sorted(expected_dirs)}")
    print()
    
    if not MEMORY_PROJECTS_DIR.exists():
        print(f"⚠️  {MEMORY_PROJECTS_DIR} does not exist")
        return []
    
    orphaned = []
    all_dirs = [d for d in MEMORY_PROJECTS_DIR.iterdir() if d.is_dir()]
    
    print(f"🔍 Scanning {len(all_dirs)} directories in {MEMORY_PROJECTS_DIR}...")
    print()
    
    for project_dir in sorted(all_dirs):
        dir_name = project_dir.name
        if dir_name not in expected_dirs:
            # Check if it's a UUID (might be a project_id that we should check)
            is_uuid = False
            try:
                import uuid
                uuid.UUID(dir_name)
                is_uuid = True
            except ValueError:
                pass
            
            # Check if this UUID matches any project ID
            matches_project_id = False
            if is_uuid:
                for project in ui_projects:
                    if project.get("id") == dir_name:
                        matches_project_id = True
                        break
            
            if not matches_project_id:
                orphaned.append((dir_name, project_dir))
    
    return orphaned


def get_directory_size(path: Path) -> int:
    """Get total size of directory in bytes"""
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except Exception:
        pass
    return total


def format_size(bytes: int) -> str:
    """Format bytes as human-readable size"""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes < 1024.0:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.1f} TB"


def main():
    import sys
    
    orphaned = find_orphaned_projects()
    
    if not orphaned:
        print("✅ No orphaned projects found!")
        return
    
    print(f"🗑️  Found {len(orphaned)} orphaned project(s):")
    print()
    
    total_size = 0
    for dir_name, project_dir in orphaned:
        size = get_directory_size(project_dir)
        total_size += size
        print(f"  • {dir_name}")
        print(f"    Path: {project_dir}")
        print(f"    Size: {format_size(size)}")
        print()
    
    print(f"📊 Total size: {format_size(total_size)}")
    print()
    
    # Ask for confirmation
    if "--dry-run" in sys.argv:
        print("🔍 DRY RUN: Would delete the above projects")
        print("   Run without --dry-run to actually delete")
        return
    
    # Skip prompt if --yes flag is provided
    if "--yes" not in sys.argv:
        response = input(f"❓ Delete {len(orphaned)} orphaned project(s)? (yes/no): ")
        if response.lower() not in ["yes", "y"]:
            print("❌ Cancelled")
            return
    
    # Delete orphaned projects
    deleted_count = 0
    deleted_size = 0
    for dir_name, project_dir in orphaned:
        try:
            size = get_directory_size(project_dir)
            shutil.rmtree(project_dir)
            deleted_count += 1
            deleted_size += size
            print(f"✅ Deleted: {dir_name} ({format_size(size)})")
        except Exception as e:
            print(f"❌ Failed to delete {dir_name}: {e}")
    
    print()
    print(f"✅ Deleted {deleted_count} project(s), freed {format_size(deleted_size)}")


if __name__ == "__main__":
    main()

