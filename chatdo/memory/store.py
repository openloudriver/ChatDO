# chatdo/memory/store.py

from __future__ import annotations

import json

from pathlib import Path

from typing import List, Dict, Any

BASE_DIR_NAME = "memory_service/projects"

def memory_root() -> Path:
    # memory_service/projects/ at the repo root
    return Path(__file__).resolve().parent.parent.parent / BASE_DIR_NAME

def thread_dir(target_name: str, thread_id: str) -> Path:
    return memory_root() / target_name / "threads" / thread_id

def thread_history_path(target_name: str, thread_id: str) -> Path:
    return thread_dir(target_name, thread_id) / "history.json"

def ensure_thread_dirs(target_name: str, thread_id: str) -> None:
    thread_dir(target_name, thread_id).mkdir(parents=True, exist_ok=True)

def load_thread_history(target_name: str, thread_id: str) -> List[Dict[str, Any]]:
    """
    Load prior messages for this target + thread.
    Format: [{"role": "user"|"assistant"|"system", "content": "..."}]
    """
    path = thread_history_path(target_name, thread_id)
    if not path.exists():
        return []
    
    try:
        return json.loads(path.read_text())
    except Exception:
        # Corrupt file? Start fresh rather than dying.
        return []

def save_thread_history(target_name: str, thread_id: str, messages: List[Dict[str, Any]]) -> None:
    ensure_thread_dirs(target_name, thread_id)
    path = thread_history_path(target_name, thread_id)
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

def delete_thread_history(target_name: str, thread_id: str) -> None:
    """
    Permanently delete thread history from disk.
    Removes the entire thread directory.
    """
    thread_path = thread_dir(target_name, thread_id)
    if thread_path.exists():
        import shutil
        shutil.rmtree(thread_path)

def thread_sources_path(target_name: str, thread_id: str) -> Path:
    return thread_dir(target_name, thread_id) / "sources.json"

def load_thread_sources(target_name: str, thread_id: str) -> List[Dict[str, Any]]:
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

def save_thread_sources(target_name: str, thread_id: str, sources: List[Dict[str, Any]]) -> None:
    ensure_thread_dirs(target_name, thread_id)
    path = thread_sources_path(target_name, thread_id)
    path.write_text(json.dumps(sources, indent=2, ensure_ascii=False))

def add_thread_source(target_name: str, thread_id: str, source: Dict[str, Any]) -> None:
    """Add a source to the thread's sources list."""
    sources = load_thread_sources(target_name, thread_id)
    # Check if source already exists (by URL or fileName)
    existing = None
    if source.get("url"):
        existing = next((s for s in sources if s.get("url") == source["url"]), None)
    elif source.get("fileName"):
        existing = next((s for s in sources if s.get("fileName") == source["fileName"]), None)
    
    if not existing:
        sources.append(source)
        save_thread_sources(target_name, thread_id, sources)

