# chatdo/memory/store.py

from __future__ import annotations

import json
import re

from pathlib import Path

from typing import List, Dict, Any, Optional

BASE_DIR_NAME = "memory_service/projects"

def memory_root() -> Path:
    # memory_service/projects/ at the repo root
    return Path(__file__).resolve().parent.parent.parent / BASE_DIR_NAME

def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')

def get_project_directory_name(project_id: Optional[str] = None, target_name: Optional[str] = None) -> str:
    """
    Get the directory name for a project in memory_service/projects/.
    
    Uses slugified project name from projects.json, or falls back to target_name or "general".
    This ensures each project has its own directory, separate from default_target.
    
    Args:
        project_id: Optional project ID to look up
        target_name: Optional target_name (for backward compatibility)
        
    Returns:
        Directory name to use in projects/ folder
    """
    if project_id:
        try:
            projects_path = Path(__file__).resolve().parent.parent.parent / "server" / "data" / "projects.json"
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
    
    # Fallback to target_name or "general"
    return target_name if target_name else "general"

def thread_dir(target_name: str, thread_id: str, project_id: Optional[str] = None) -> Path:
    """
    Get the thread directory path.
    
    Uses project directory name (slugified project name) instead of target_name
    to ensure each project has its own folder.
    """
    project_dir_name = get_project_directory_name(project_id=project_id, target_name=target_name)
    return memory_root() / project_dir_name / "threads" / thread_id

def thread_history_path(target_name: str, thread_id: str, project_id: Optional[str] = None) -> Path:
    return thread_dir(target_name, thread_id, project_id=project_id) / "history.json"

def ensure_thread_dirs(target_name: str, thread_id: str, project_id: Optional[str] = None) -> None:
    thread_dir(target_name, thread_id, project_id=project_id).mkdir(parents=True, exist_ok=True)

def load_thread_history(target_name: str, thread_id: str, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Load prior messages for this target + thread.
    Format: [{"role": "user"|"assistant"|"system", "content": "..."}]
    
    Tries new location (project directory name) first, then falls back to old location (default_target)
    for backward compatibility with existing threads.
    """
    # Try new location first (using project directory name)
    path = thread_history_path(target_name, thread_id, project_id=project_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            # Corrupt file? Try fallback location
            pass
    
    # Fallback: try old location (using default_target/target_name) for backward compatibility
    if project_id:
        try:
            projects_path = Path(__file__).resolve().parent.parent.parent / "server" / "data" / "projects.json"
            if projects_path.exists():
                with open(projects_path, 'r') as f:
                    projects = json.load(f)
                    for project in projects:
                        if project.get("id") == project_id:
                            old_target = project.get("default_target")
                            if old_target and old_target != target_name:
                                # Try loading from old location
                                old_path = memory_root() / old_target / "threads" / thread_id / "history.json"
                                if old_path.exists():
                                    try:
                                        return json.loads(old_path.read_text())
                                    except Exception:
                                        pass
                            break
        except Exception:
            pass
    
    return []

def save_thread_history(target_name: str, thread_id: str, messages: List[Dict[str, Any]], project_id: Optional[str] = None) -> None:
    ensure_thread_dirs(target_name, thread_id, project_id=project_id)
    path = thread_history_path(target_name, thread_id, project_id=project_id)
    path.write_text(json.dumps(messages, indent=2, ensure_ascii=False))
    
    # Index new messages into Memory Service (async, non-blocking)
    # Only index the last message(s) that were just added
    try:
        # Try to load previous history to see what's new
        try:
            old_messages = json.loads(path.read_text()) if path.exists() else []
        except:
            old_messages = []
        
        # Find new messages (those not in old_messages)
        old_message_ids = {msg.get("id") for msg in old_messages if msg.get("id")}
        new_messages = [msg for msg in messages if msg.get("id") and msg.get("id") not in old_message_ids]
        
        # If we can't determine what's new, index the last message
        if not new_messages and messages:
            new_messages = [messages[-1]]
        
        # Index new messages
        if new_messages:
            # Get project_id from target_name or from message metadata
            # For now, we'll need to get it from the project config
            # This is a simplified approach - in practice, you'd pass project_id explicitly
            project_id = None
            try:
                from pathlib import Path
                projects_path = Path(__file__).parent.parent.parent / "server" / "data" / "projects.json"
                if projects_path.exists():
                    import json as json_module
                    with open(projects_path, 'r') as f:
                        projects = json_module.load(f)
                        # Find project by default_target matching target_name
                        for project in projects:
                            if project.get("default_target") == target_name:
                                project_id = project.get("id")
                                break
            except Exception:
                pass
            
            if project_id:
                from server.services.memory_service_client import get_memory_client
                client = get_memory_client()
                
                for msg in new_messages:
                    role = msg.get("role")
                    content = msg.get("content", "")
                    message_id = msg.get("id", "")
                    
                    # Only index user and assistant messages (not system)
                    if role in ("user", "assistant") and content and message_id:
                        # Get created_at timestamp (canonical field name)
                        timestamp = msg.get("created_at") or msg.get("timestamp")  # Support both for backward compatibility
                        if not timestamp:
                            from datetime import datetime, timezone
                            timestamp = datetime.now(timezone.utc).isoformat()
                        elif isinstance(timestamp, str):
                            pass  # Already ISO string
                        else:
                            timestamp = timestamp.isoformat()
                        
                        # Get message index
                        message_index = len([m for m in messages if m.get("role") == role])
                        
                        # Index asynchronously (fire and forget)
                        try:
                            client.index_chat_message(
                                project_id=project_id,
                                chat_id=thread_id,
                                message_id=message_id,
                                role=role,
                                content=content,
                                timestamp=timestamp,
                                message_index=message_index
                            )
                        except Exception as e:
                            # Log but don't fail - indexing is best effort
                            import logging
                            logging.getLogger(__name__).debug(f"Failed to index message {message_id}: {e}")
    except Exception as e:
        # Don't fail if indexing fails - it's best effort
        import logging
        logging.getLogger(__name__).debug(f"Failed to index messages: {e}")

def delete_thread_history(target_name: str, thread_id: str, project_id: Optional[str] = None) -> None:
    """
    Permanently delete thread history from disk.
    Removes the entire thread directory.
    """
    thread_path = thread_dir(target_name, thread_id, project_id=project_id)
    if thread_path.exists():
        import shutil
        shutil.rmtree(thread_path)

def thread_sources_path(target_name: str, thread_id: str, project_id: Optional[str] = None) -> Path:
    return thread_dir(target_name, thread_id, project_id=project_id) / "sources.json"

def load_thread_sources(target_name: str, thread_id: str, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Load sources for this target + thread.
    Format: [{"id": "...", "kind": "url|file|text|note", "title": "...", ...}]
    """
    path = thread_sources_path(target_name, thread_id)
    if not path.exists():
        return []
    
    try:
        return json.loads(path.read_text())
    except Exception:
        return []

def save_thread_sources(target_name: str, thread_id: str, sources: List[Dict[str, Any]], project_id: Optional[str] = None) -> None:
    ensure_thread_dirs(target_name, thread_id, project_id=project_id)
    path = thread_sources_path(target_name, thread_id, project_id=project_id)
    path.write_text(json.dumps(sources, indent=2, ensure_ascii=False))

def add_thread_source(target_name: str, thread_id: str, source: Dict[str, Any], project_id: Optional[str] = None) -> None:
    """Add a source to the thread's sources list."""
    sources = load_thread_sources(target_name, thread_id, project_id=project_id)
    # Check if source already exists (by URL or fileName)
    existing = None
    if source.get("url"):
        existing = next((s for s in sources if s.get("url") == source["url"]), None)
    elif source.get("fileName"):
        existing = next((s for s in sources if s.get("fileName") == source["fileName"]), None)
    
    if not existing:
        sources.append(source)
        save_thread_sources(target_name, thread_id, sources, project_id=project_id)

