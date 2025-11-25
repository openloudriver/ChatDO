"""
File system watcher that keeps the index up to date.

Uses watchdog to monitor configured source folders for file changes.
"""
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from typing import Dict

from memory_service.config import load_sources
from memory_service.store import db
from memory_service.indexer import index_file, delete_file, should_index_file

logger = logging.getLogger(__name__)


class IndexingHandler(FileSystemEventHandler):
    """Handler for file system events that triggers indexing."""
    
    def __init__(self, source_db_id: int, source_id: str, root_path: Path, include_glob: str, exclude_glob: str):
        self.source_db_id = source_db_id
        self.source_id = source_id
        self.root_path = root_path
        self.include_glob = include_glob
        self.exclude_glob = exclude_glob
    
    def on_created(self, event: FileSystemEvent):
        """Handle file creation."""
        if event.is_directory:
            return
        
        path = Path(event.src_path)
        if should_index_file(path, self.include_glob, self.exclude_glob):
            logger.info(f"File created, indexing: {path}")
            index_file(path, self.source_db_id, self.source_id)
    
    def on_modified(self, event: FileSystemEvent):
        """Handle file modification."""
        if event.is_directory:
            return
        
        path = Path(event.src_path)
        if should_index_file(path, self.include_glob, self.exclude_glob):
            logger.info(f"File modified, re-indexing: {path}")
            index_file(path, self.source_db_id, self.source_id)
    
    def on_deleted(self, event: FileSystemEvent):
        """Handle file deletion."""
        if event.is_directory:
            return
        
        path = Path(event.src_path)
        logger.info(f"File deleted, removing from index: {path}")
        delete_file(path, self.source_db_id, self.source_id)


class WatcherManager:
    """Manages file system watchers for all configured sources."""
    
    def __init__(self):
        self.observers: Dict[str, Observer] = {}
    
    def start_all(self):
        """Start watching all configured sources."""
        sources = load_sources()
        
        for source_config in sources:
            # Ensure source exists in database
            db_id = db.upsert_source(
                source_config.id,
                source_config.project_id,
                str(source_config.root_path),
                source_config.include_glob,
                source_config.exclude_glob
            )
            
            # Start watching
            self.start_watching(source_config.id, db_id, source_config.root_path, 
                              source_config.include_glob, source_config.exclude_glob)
    
    def start_watching(self, source_id: str, db_id: int, root_path: Path, 
                      include_glob: str, exclude_glob: str):
        """Start watching a specific source."""
        if not root_path.exists():
            logger.warning(f"Source root path does not exist, skipping watch: {root_path}")
            return
        
        if source_id in self.observers:
            logger.warning(f"Already watching source: {source_id}")
            return
        
        observer = Observer()
        handler = IndexingHandler(db_id, source_id, root_path, include_glob, exclude_glob)
        observer.schedule(handler, str(root_path), recursive=True)
        observer.start()
        
        self.observers[source_id] = observer
        logger.info(f"Started watching source: {source_id} at {root_path}")
    
    def stop_all(self):
        """Stop all watchers."""
        for source_id, observer in self.observers.items():
            observer.stop()
            observer.join()
            logger.info(f"Stopped watching source: {source_id}")
        
        self.observers.clear()

