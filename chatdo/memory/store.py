# chatdo/memory/store.py

from __future__ import annotations

import json

from pathlib import Path

from typing import List, Dict, Any

BASE_DIR_NAME = "memory"

def memory_root() -> Path:
    # memory/ at the repo root
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

