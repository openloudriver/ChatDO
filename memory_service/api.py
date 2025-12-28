"""
HTTP interface for ChatDO → Memory Service communication.

Provides REST API endpoints for health checks, source management, indexing, and search.
"""
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import numpy as np
from contextlib import asynccontextmanager
import asyncio
import threading

from memory_service.config import API_HOST, API_PORT, EMBEDDING_MODEL, EMBEDDING_DIM, load_sources, create_dynamic_source, BASE_DIR, MEMORY_DASHBOARD_PATH, DYNAMIC_SOURCES_PATH, MEMORY_SOURCES_YAML, load_dynamic_sources, save_dynamic_sources, load_static_sources
from memory_service.memory_dashboard import db
from memory_service.indexer import index_source, index_chat_message
from memory_service.indexing_queue import get_indexing_queue
from memory_service.watcher import WatcherManager
from memory_service.vector_cache import get_query_embedding
from memory_service.ann_index import AnnIndexManager
from memory_service.models import SourceStatus, IndexJob, FileTreeResponse, FileReadResponse
from memory_service.filetree import FileTreeManager
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global watcher manager
watcher_manager = WatcherManager()

# Global ANN index manager
ann_index_manager = AnnIndexManager(dimension=EMBEDDING_DIM)

# Global FileTree manager
filetree_manager = FileTreeManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup
    logger.info("Initializing Memory Service...")
    
    # Check for existing instance before starting
    try:
        from memory_service.startup_check import (
            check_existing_instance,
            create_pid_file,
            remove_pid_file,
            acquire_lock,
            release_lock
        )
        
        is_running, message = check_existing_instance(API_HOST, API_PORT)
        if is_running:
            logger.error(f"[STARTUP] {message}")
            logger.error("[STARTUP] Exiting to prevent duplicate instance")
            raise RuntimeError(f"Cannot start: {message}")
        
        # Acquire lock to prevent race conditions
        if not acquire_lock():
            logger.error("[STARTUP] Failed to acquire lock - another instance may be starting")
            raise RuntimeError("Failed to acquire lock - another instance may be starting")
        
        # Create PID file
        if not create_pid_file():
            logger.warning("[STARTUP] Failed to create PID file (continuing anyway)")
        
        logger.info("[STARTUP] No existing instance detected, proceeding with startup")
    except ImportError:
        # startup_check module not available - skip checks (for development)
        logger.warning("[STARTUP] startup_check module not available, skipping duplicate check")
    except RuntimeError as e:
        # Re-raise startup errors
        raise
    except Exception as e:
        logger.warning(f"[STARTUP] Error during startup check: {e} (continuing anyway)")
    # Initialize tracking database
    db.init_tracking_db()
    logger.info("Tracking database initialized")
    
    # Register all sources from config (static + dynamic) into tracking DB
    sources = load_sources()
    for source_config in sources:
        db.get_or_create_source(
            source_config.id,
            str(source_config.root_path),
            getattr(source_config, 'display_name', source_config.id),
            source_config.project_id
        )
    logger.info(f"Registered {len(sources)} sources in tracking database")
    
    # Note: Per-source databases are initialized on first use
    logger.info("Database system ready")
    
    # Start indexing queue workers
    indexing_queue = get_indexing_queue()
    indexing_queue.start()
    logger.info("Indexing queue started")
    
    # Build ANN index in background thread (non-blocking)
    def build_ann_index_background():
        _build_ann_index()
    
    ann_thread = threading.Thread(target=build_ann_index_background, daemon=True)
    ann_thread.start()
    logger.info("ANN index build started in background thread")
    
    # Load sources from config and start watchers
    watcher_manager.start_all()
    logger.info("File watchers started")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Memory Service...")
    watcher_manager.stop_all()
    logger.info("File watchers stopped")
    
    # Stop indexing queue
    indexing_queue = get_indexing_queue()
    indexing_queue.stop()
    logger.info("Indexing queue stopped")
    
    # Clean up PID file and lock
    try:
        from memory_service.startup_check import remove_pid_file, release_lock
        remove_pid_file()
        release_lock()
        logger.info("[SHUTDOWN] Cleaned up PID file and lock")
    except Exception as e:
        logger.warning(f"[SHUTDOWN] Error cleaning up: {e}")


app = FastAPI(title="Memory Service", version="1.0.0", lifespan=lifespan)

# Add CORS middleware to allow frontend connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class ReindexRequest(BaseModel):
    source_id: str


class AddSourceRequest(BaseModel):
    root_path: str
    display_name: Optional[str] = None
    project_id: Optional[str] = "general"


class SearchRequest(BaseModel):
    project_id: str
    query: str
    limit: int = 10
    source_ids: Optional[List[str]] = None
    chat_id: Optional[str] = None  # DEPRECATED: No longer excludes chats. All chats are included.
    exclude_chat_ids: Optional[List[str]] = None  # List of chat_ids to exclude from search (e.g., trashed chats)


class SearchResult(BaseModel):
    score: float
    project_id: str
    source_id: str
    file_path: Optional[str] = None
    filetype: Optional[str] = None
    chunk_index: int
    text: str
    start_char: int
    end_char: int
    source_type: str = "file"  # "file" or "chat"
    chat_id: Optional[str] = None
    message_id: Optional[str] = None
    message_uuid: Optional[str] = None  # UUID for citations/deep-links


class IndexChatMessageRequest(BaseModel):
    project_id: str
    chat_id: str
    message_id: str
    role: str
    content: str
    timestamp: str  # ISO format datetime string
    message_index: int


class SearchResponse(BaseModel):
    results: List[SearchResult]


# REMOVED: NEW facts table system models
# - StoreFactRequest
# - GetFactsRequest  
# - StructuredFactResponse
# - FactsResponse
# All fact operations now use project_facts table via /search-facts endpoint


def _build_ann_index():
    """Load all embeddings from all sources and build ANN index."""
    if not ann_index_manager.is_available():
        logger.warning("[ANN] FAISS not available, skipping ANN index build")
        return
    
    logger.info("[ANN] Building FAISS IndexFlatIP index...")
    
    try:
        # Get all sources from tracking DB
        sources_with_jobs = db.get_all_sources_with_latest_job()
        all_sources = [source for source, _ in sources_with_jobs]
        
        # Also get all project IDs for chat sources
        project_ids = set()
        for source in all_sources:
            if source.project_id:
                project_ids.add(source.project_id)
        
        total_embeddings = 0
        
        # Load embeddings from all file sources
        for source in all_sources:
            source_id = source.id
            try:
                # Skip chat sources (handled separately)
                if source_id.startswith("project-"):
                    continue
                
                # Check if source database exists
                from memory_service.config import get_db_path_for_source
                db_path = get_db_path_for_source(source_id)
                if not db_path.exists():
                    continue
                
                embeddings_data = db.get_all_embeddings_for_source(source_id, EMBEDDING_MODEL)
                
                if len(embeddings_data) == 0:
                    continue
                
                # Prepare vectors and metadata
                vectors = []
                metadata_list = []
                
                for chunk_id, embedding, file_id, file_path, chunk_text, src_id, project_id, filetype, chunk_index, start_char, end_char, chat_id, message_id in embeddings_data:
                    vectors.append(embedding)
                    metadata_list.append({
                        "embedding_id": chunk_id,  # Use chunk_id as embedding_id for now
                        "chunk_id": chunk_id,
                        "file_id": file_id,
                        "file_path": file_path,
                        "chunk_text": chunk_text,
                        "source_id": src_id,
                        "project_id": project_id,
                        "filetype": filetype,
                        "chunk_index": chunk_index,
                        "start_char": start_char,
                        "end_char": end_char,
                        "chat_id": chat_id,
                        "message_id": message_id,
                    })
                
                if len(vectors) > 0:
                    # Process in batches to avoid overwhelming FAISS and prevent crashes
                    BATCH_SIZE = 1000  # Process 1000 embeddings at a time
                    for batch_start in range(0, len(vectors), BATCH_SIZE):
                        batch_end = min(batch_start + BATCH_SIZE, len(vectors))
                        batch_vectors = vectors[batch_start:batch_end]
                        batch_metadata = metadata_list[batch_start:batch_end]
                        
                        vectors_array = np.array(batch_vectors, dtype=np.float32)
                        ann_index_manager.add_embeddings(vectors_array, batch_metadata)
                        total_embeddings += len(batch_vectors)
                        
                        # Small delay between batches to avoid overwhelming the system
                        import time
                        time.sleep(0.01)
                    
                    logger.debug(f"[ANN] Loaded {len(vectors)} embeddings from source {source_id} in batches")
                
            except Exception as e:
                logger.warning(f"[ANN] Error loading embeddings from source {source_id}: {e}")
                continue
        
        # Load embeddings from all chat sources
        for project_id in project_ids:
            try:
                chat_embeddings = db.get_chat_embeddings_for_project(project_id, EMBEDDING_MODEL, exclude_chat_id=None)
                
                if len(chat_embeddings) == 0:
                    continue
                
                # Prepare vectors and metadata
                vectors = []
                metadata_list = []
                
                for chunk_id, embedding, file_id, file_path, chunk_text, src_id, project_id_val, filetype, chunk_index, start_char, end_char, chat_id, message_id in chat_embeddings:
                    vectors.append(embedding)
                    metadata_list.append({
                        "embedding_id": chunk_id,  # Use chunk_id as embedding_id
                        "chunk_id": chunk_id,
                        "file_id": file_id,
                        "file_path": file_path,
                        "chunk_text": chunk_text,
                        "source_id": src_id,
                        "project_id": project_id_val,
                        "filetype": filetype,
                        "chunk_index": chunk_index,
                        "start_char": start_char,
                        "end_char": end_char,
                        "chat_id": chat_id,
                        "message_id": message_id,
                    })
                
                if len(vectors) > 0:
                    # Process in batches
                    BATCH_SIZE = 1000
                    for batch_start in range(0, len(vectors), BATCH_SIZE):
                        batch_end = min(batch_start + BATCH_SIZE, len(vectors))
                        batch_vectors = vectors[batch_start:batch_end]
                        batch_metadata = metadata_list[batch_start:batch_end]
                        
                        vectors_array = np.array(batch_vectors, dtype=np.float32)
                        ann_index_manager.add_embeddings(vectors_array, batch_metadata)
                        total_embeddings += len(batch_vectors)
                        
                        import time
                        time.sleep(0.01)
                    
                    logger.debug(f"[ANN] Loaded {len(vectors)} chat embeddings for project {project_id} in batches")
                
            except Exception as e:
                logger.warning(f"[ANN] Error loading chat embeddings for project {project_id}: {e}")
                continue
        
        logger.info(f"[ANN] FAISS index ready (dim={EMBEDDING_DIM}, size={ann_index_manager.get_index_size()})")
        
    except Exception as e:
        logger.error(f"[ANN] Error building ANN index: {e}", exc_info=True)
        logger.warning("[ANN] Falling back to brute-force vector search")


# Endpoints
@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/sources")
async def get_sources():
    """Get list of all sources with status and latest job."""
    sources_with_jobs = db.get_all_sources_with_latest_job()
    
    # Load projects to find which projects are connected to each source
    projects_map = {}  # source_id -> list of project names
    try:
        projects_path = BASE_DIR / "server" / "data" / "projects.json"
        if projects_path.exists():
            import json
            with open(projects_path, 'r') as pf:
                projects = json.load(pf)
                for project in projects:
                    project_name = project.get("name", project.get("id", "Unknown"))
                    for source_id in project.get("memory_sources", []):
                        if source_id not in projects_map:
                            projects_map[source_id] = []
                        projects_map[source_id].append(project_name)
    except Exception as e:
        logger.warning(f"Could not load projects.json for connected projects: {e}")
        pass
    
    result = []
    for source, latest_job in sources_with_jobs:
        # Get connected project names for this source
        connected_projects = projects_map.get(source.id, [])
        
        source_dict = {
            "id": source.id,
            "display_name": source.display_name,
            "root_path": source.root_path,
            "status": source.status,
            "files_indexed": source.files_indexed,
            "bytes_indexed": source.bytes_indexed,
            "last_index_started_at": source.last_index_started_at.isoformat() if source.last_index_started_at else None,
            "last_index_completed_at": source.last_index_completed_at.isoformat() if source.last_index_completed_at else None,
            "last_error": source.last_error,
            "project_id": source.project_id,  # Keep for backward compatibility
            "connected_projects": connected_projects,  # New: list of project names
            "latest_job": None
        }
        
        if latest_job:
            source_dict["latest_job"] = {
                "id": latest_job.id,
                "status": latest_job.status,
                "files_total": latest_job.files_total,
                "files_processed": latest_job.files_processed,
                "bytes_processed": latest_job.bytes_processed,
                "started_at": latest_job.started_at.isoformat(),
                "completed_at": latest_job.completed_at.isoformat() if latest_job.completed_at else None,
                "error": latest_job.error
            }
        
        result.append(source_dict)
    
    return {"sources": result}


@app.post("/sources")
async def add_source(request: AddSourceRequest):
    """Create a new dynamic memory source and start indexing it."""
    try:
        # Create the source config
        src = create_dynamic_source(
            root_path=request.root_path,
            display_name=request.display_name,
            project_id=request.project_id or "general",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Register in tracking DB
    status = db.register_source_config(src)
    
    # Start watching this path
    watcher_manager.add_source_watch(src)
    
    # Kick off indexing in background thread
    def run_indexing():
        try:
            index_source(src.id)
        except Exception as e:
            logger.error(f"Background indexing failed for {src.id}: {e}", exc_info=True)
            db.update_source_stats(
                src.id,
                status="error",
                last_error=str(e)
            )
    
    thread = threading.Thread(target=run_indexing, daemon=True)
    thread.start()
    
    return {
        "status": "ok",
        "source_id": src.id,
        "display_name": getattr(src, 'display_name', src.id),
        "root_path": str(src.root_path),
        "project_id": src.project_id,
        "files_indexed": 0,
        "bytes_indexed": 0,
        "job_id": 0,  # Will be available via /sources endpoint
    }


@app.delete("/sources/{source_id}")
async def delete_source(source_id: str):
    """Delete a memory source (both static and dynamic sources can be deleted)."""
    import shutil
    import json
    import yaml
    
    # Check if it's a dynamic source
    dynamic_sources = load_dynamic_sources()
    is_dynamic = any(src.id == source_id for src in dynamic_sources)
    
    # Check if it's a static source
    static_sources = load_static_sources()
    is_static = any(src.id == source_id for src in static_sources)
    
    # Check if it exists in tracking DB (even if not in config files)
    source_status = db.get_source_status(source_id)
    exists_in_tracking = source_status is not None
    
    # If not found in config files or tracking DB, return 404
    if not is_dynamic and not is_static and not exists_in_tracking:
        raise HTTPException(
            status_code=404, 
            detail=f"Source '{source_id}' not found"
        )
    
    # Remove from projects.json connections
    try:
        projects_path = BASE_DIR / "server" / "data" / "projects.json"
        if projects_path.exists():
            with open(projects_path, 'r') as pf:
                projects = json.load(pf)
            
            updated = False
            for project in projects:
                if source_id in project.get("memory_sources", []):
                    project["memory_sources"] = [s for s in project["memory_sources"] if s != source_id]
                    updated = True
            
            if updated:
                # Atomic write to projects.json
                import tempfile
                import shutil
                temp_path = projects_path.with_suffix('.json.tmp')
                with open(temp_path, 'w') as pf:
                    json.dump(projects, pf, indent=2)
                shutil.move(str(temp_path), str(projects_path))
                logger.info(f"Removed {source_id} from project connections")
    except Exception as e:
        logger.error(f"Could not update projects.json: {e}", exc_info=True)
    
    # Stop watching this source
    try:
        watcher_manager.stop_watching(source_id)
    except Exception as e:
        logger.warning(f"Could not stop watcher for {source_id}: {e}")
    
    # Remove from dynamic_sources.json if it's a dynamic source
    if is_dynamic:
        dynamic_sources = [s for s in dynamic_sources if s.id != source_id]
        save_dynamic_sources(dynamic_sources)
        logger.info(f"Removed {source_id} from dynamic_sources.json")
    
    # Remove from memory_sources.yaml if it's a static source
    if is_static:
        if MEMORY_SOURCES_YAML.exists():
            with open(MEMORY_SOURCES_YAML, 'r') as f:
                config = yaml.safe_load(f) or {}
            
            sources = config.get("sources", [])
            config["sources"] = [s for s in sources if s.get("id") != source_id]
            
            with open(MEMORY_SOURCES_YAML, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            logger.info(f"Removed {source_id} from memory_sources.yaml")
    
    # Always remove from tracking DB (even if not in config files)
    if exists_in_tracking:
        db.delete_source_from_tracking(source_id)
        logger.info(f"Removed {source_id} from tracking database")
    
    # Delete the index directory (frees up disk space; can always re-index if source is re-added)
    # Handle project sources vs file sources differently
    if source_id.startswith("project-"):
        # Project sources are in projects/<project_name>/index/
        from memory_service.config import PROJECTS_PATH, get_project_directory_name
        project_id = source_id.replace("project-", "")
        
        # Get project directory name (slugified project name, not default_target)
        project_dir_name = get_project_directory_name(project_id)
        
        index_dir = PROJECTS_PATH / project_dir_name / "index"
        if index_dir.exists():
            try:
                # Delete the index.sqlite file and related files
                for file in index_dir.glob("index.sqlite*"):
                    file.unlink()
                logger.info(f"Deleted project index directory for source: {source_id} (project: {project_dir_name})")
            except Exception as e:
                logger.warning(f"Could not delete project index directory for {source_id}: {e}")
    else:
        # File sources are in memory_dashboard/<source_id>/
        source_dir = MEMORY_DASHBOARD_PATH / source_id
        if source_dir.exists():
            try:
                shutil.rmtree(source_dir, ignore_errors=True)
                logger.info(f"Deleted index directory for source: {source_id}")
            except Exception as e:
                logger.warning(f"Could not delete index directory for {source_id}: {e}")
    
    return {
        "status": "ok",
        "message": f"Source '{source_id}' deleted successfully"
    }


@app.post("/reindex")
async def reindex(request: ReindexRequest):
    """Trigger a full reindex of a source."""
    logger.info(f"[MEMORY] Reindex requested: {request.source_id}")
    try:
        # First, try to get source from config files
        sources = load_sources()
        source_config = None
        for s in sources:
            if s.id == request.source_id:
                source_config = s
                break
        
        # If not in config, check tracking database
        if not source_config:
            try:
                # Get source from tracking database
                source_status = db.get_source_status(request.source_id)
                if source_status:
                    # Create a SourceConfig from the tracking DB entry
                    from memory_service.config import SourceConfig
                    source_config = SourceConfig({
                        "id": source_status.id,
                        "project_id": source_status.project_id or "general",
                        "root_path": source_status.root_path,
                        "include_glob": "**/*",  # Default since not stored in tracking DB
                        "exclude_glob": "",  # Default since not stored in tracking DB
                        "display_name": source_status.display_name
                    })
                    logger.info(f"Found source {request.source_id} in tracking database, using it for reindex")
            except Exception as e:
                logger.warning(f"Error checking tracking database for source {request.source_id}: {e}")
        
        if not source_config:
            raise HTTPException(status_code=404, detail=f"Source not found: {request.source_id}")
        
        # Initialize database and register source FIRST (before deleting anything)
        # This ensures the source exists when index_source() tries to find it
        db.init_db(request.source_id)
        db_id = db.upsert_source(
            source_config.id,
            source_config.project_id,
            str(source_config.root_path),
            source_config.include_glob,
            source_config.exclude_glob
        )
        logger.info(f"[MEMORY] Registered source {request.source_id} in database (db_id: {db_id})")
        
        # Clear old index data (files, chunks, embeddings) but keep the source record
        # We do this by deleting files/chunks/embeddings from the database, not deleting the directory
        # Note: For project sources, the path is in projects/<project_name>/index/, but we don't need it here
        
        # Delete all files/chunks/embeddings for this source from the database
        conn = db.get_db_connection(request.source_id)
        cursor = conn.cursor()
        try:
            # Delete embeddings first (foreign key constraint)
            cursor.execute("DELETE FROM embeddings")
            # Delete chunks
            cursor.execute("DELETE FROM chunks")
            # Delete files
            cursor.execute("DELETE FROM files")
            conn.commit()
            logger.info(f"[MEMORY] Cleared old index data (files/chunks/embeddings) for source: {request.source_id}")
        except Exception as e:
            logger.warning(f"[MEMORY] Error clearing old index data: {e}")
            conn.rollback()
        finally:
            conn.close()
        
        # Update source status to "indexing" immediately
        db.update_source_stats(
            request.source_id,
            status="indexing",
            last_index_started_at=datetime.now()
        )
        logger.info(f"[MEMORY] Set source {request.source_id} status to 'indexing'")
        
        # Run indexing in background thread to avoid blocking the API
        def run_indexing():
            try:
                logger.info(f"[MEMORY] Starting background indexing for {request.source_id}")
                # Give the API response time to return before starting heavy work
                import time
                time.sleep(0.5)
                result = index_source(request.source_id)
                logger.info(f"[MEMORY] Background indexing completed for {request.source_id}: {result}")
            except Exception as e:
                logger.error(f"[MEMORY] Background indexing failed for {request.source_id}: {e}", exc_info=True)
                db.update_source_stats(
                    request.source_id,
                    status="error",
                    last_error=str(e)
                )
        
        thread = threading.Thread(target=run_indexing, daemon=True)
        thread.start()
        logger.info(f"[MEMORY] Background thread started for {request.source_id}, thread ID: {thread.ident}")
        
        logger.info(f"[MEMORY] Reindex request accepted for {request.source_id}, background job started")
        
        # Return immediately - client can poll /sources to get the job_id
        return {
            "status": "ok",
            "files_indexed": 0,
            "bytes_indexed": 0,
            "job_id": 0,  # Will be available via /sources endpoint
            "source_id": request.source_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reindexing source {request.source_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sources/{source_id}/status")
async def get_source_status(source_id: str):
    """Get status for a specific source."""
    source_status = db.get_or_create_source(source_id, "", source_id)
    latest_job = db.get_latest_job(source_id)
    
    result = {
        "id": source_status.id,
        "display_name": source_status.display_name,
        "root_path": source_status.root_path,
        "status": source_status.status,
        "files_indexed": source_status.files_indexed,
        "bytes_indexed": source_status.bytes_indexed,
        "last_index_started_at": source_status.last_index_started_at.isoformat() if source_status.last_index_started_at else None,
        "last_index_completed_at": source_status.last_index_completed_at.isoformat() if source_status.last_index_completed_at else None,
        "last_error": source_status.last_error,
        "project_id": source_status.project_id,
        "latest_job": None
    }
    
    if latest_job:
        result["latest_job"] = {
            "id": latest_job.id,
            "status": latest_job.status,
            "files_total": latest_job.files_total,
            "files_processed": latest_job.files_processed,
            "bytes_processed": latest_job.bytes_processed,
            "started_at": latest_job.started_at.isoformat(),
            "completed_at": latest_job.completed_at.isoformat() if latest_job.completed_at else None,
            "error": latest_job.error
        }
    
    return result


@app.get("/sources/{source_id}/jobs")
async def get_source_jobs(source_id: str, limit: int = 10):
    """Get recent jobs for a source."""
    jobs = db.get_recent_jobs(source_id, limit)
    
    return {
        "jobs": [
            {
                "id": job.id,
                "source_id": job.source_id,
                "status": job.status,
                "started_at": job.started_at.isoformat(),
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "files_total": job.files_total,
                "files_processed": job.files_processed,
                "bytes_processed": job.bytes_processed,
                "error": job.error
            }
            for job in jobs
        ]
    }


@app.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest):
    """
    Search for relevant chunks by source_ids and query.
    
    Returns top-N matches ordered by cosine similarity.
    If source_ids is not provided, returns empty results.
    
    Uses query expansion to improve recall for table-heavy documents.
    
    PROJECT ISOLATION:
    - Chat sources (source_id starts with "project-"): Strict project isolation - must match project_id
    - File sources: If source_id is in source_ids (connected to this project via projects.json), 
      allow cross-project access. This enables sharing file sources across projects without reindexing.
    """
    try:
        # HARD INVARIANT: project_id is required and must not be None/empty
        if not request.project_id or request.project_id.strip() == "":
            logger.error(f"[ISOLATION] Search rejected: project_id is missing or empty")
            raise HTTPException(status_code=400, detail="project_id is required and cannot be empty")
        
        # Debug logging for every memory query
        exclude_count = len(request.exclude_chat_ids) if request.exclude_chat_ids else 0
        logger.info(f"[MEMORY-QUERY] project_id={request.project_id}, chat_id={request.chat_id}, limit={request.limit}, source_ids={request.source_ids}, exclude_chat_ids={exclude_count} chats")
        # Query expansion: extract key terms and search for them individually
        # Note: We allow empty source_ids to enable chat-only searches
        # This helps with table-heavy PDFs where the full query might not match well
        query_terms = []
        original_query = request.query.lower()
        
        # Extract potential key terms (words that look important)
        words = original_query.split()
        for word in words:
            # Keep words that are likely meaningful (not common stop words)
            if len(word) > 3 and word not in ['the', 'what', 'when', 'where', 'which', 'this', 'that', 'with', 'from']:
                query_terms.append(word)
        
        # Also try the original query
        all_queries = [request.query] + query_terms[:3]  # Limit to top 3 terms to avoid too many searches
        
        # Embed all query variations (using cached query embeddings)
        query_embeddings = [get_query_embedding(q) for q in all_queries]
        
        # Use primary query embedding for ANN search
        primary_query_embedding = query_embeddings[0]
        
        # Determine which sources to search
        filter_source_ids = request.source_ids if request.source_ids else None
        
        # Try ANN search first
        use_ann = ann_index_manager.is_available()
        ann_results = []
        
        if use_ann:
            try:
                logger.info(f"[ANN] Using FAISS IndexFlatIP for vector search (k={request.limit * 2}, project_id={request.project_id})")
                # Search for more results to account for filtering
                ann_results = ann_index_manager.search(
                    primary_query_embedding,
                    top_k=request.limit * 2,  # Get more candidates
                    filter_source_ids=filter_source_ids,
                    filter_project_id=request.project_id,  # CRITICAL: Filter by project_id for isolation
                    exclude_chat_ids=request.exclude_chat_ids  # CRITICAL: Exclude trashed chats
                )
            except Exception as e:
                logger.warning(f"[ANN] ANN search failed, falling back to brute-force: {e}")
                use_ann = False
        
        # Fallback to brute-force if ANN unavailable or failed
        if not use_ann or len(ann_results) == 0:
            logger.info("[ANN] ANN unavailable, falling back to brute-force")
            
            # Load all embeddings from specified sources
            all_embeddings = []
            if request.source_ids:  # Only search file sources if source_ids is provided
                for source_id in request.source_ids:
                    try:
                        source_embeddings = db.get_all_embeddings_for_source(source_id, EMBEDDING_MODEL)
                        all_embeddings.extend(source_embeddings)
                    except Exception as e:
                        logger.warning(f"Error searching source {source_id}: {e}")
                        continue
            
            # Also search chat messages for this project (exclude trashed chats)
            try:
                chat_embeddings = db.get_chat_embeddings_for_project(
                    request.project_id, 
                    EMBEDDING_MODEL, 
                    exclude_chat_id=None,  # Backward compatibility
                    exclude_chat_ids=request.exclude_chat_ids  # Exclude trashed chats
                )
                all_embeddings.extend(chat_embeddings)
            except Exception as e:
                logger.debug(f"Error searching chat messages for project {request.project_id}: {e}")
            
            if not all_embeddings:
                return SearchResponse(results=[])
            
            # Compute vector scores using brute-force
            ann_results = []
            for chunk_id, embedding, file_id, file_path, chunk_text, source_id, project_id, filetype, chunk_index, start_char, end_char, chat_id, message_id, message_uuid in all_embeddings:
                # PROJECT ISOLATION LOGIC:
                # - Chat sources (source_id starts with "project-"): Strict project isolation - must match project_id
                # - File sources: If source_id is in request.source_ids (connected to this project), allow cross-project access
                #   This enables sharing file sources across projects without reindexing
                is_chat_source = source_id and source_id.startswith("project-")
                if is_chat_source:
                    # Chat sources: strict isolation - must match project_id
                    if project_id != request.project_id:
                        continue
                else:
                    # File sources: if source_id is in allowed list, allow it (cross-project access)
                    # Note: source_ids were already filtered when loading embeddings above,
                    # so if we get here with a file source, it's allowed regardless of project_id
                    pass
                
                # Vector similarity (cosine similarity) - try all query variations and take best
                best_vector_score = 0.0
                for query_embedding in query_embeddings:
                    dot_product = np.dot(query_embedding, embedding)
                    norm_query = np.linalg.norm(query_embedding)
                    norm_embedding = np.linalg.norm(embedding)
                    
                    if norm_query > 0 and norm_embedding > 0:
                        similarity = dot_product / (norm_query * norm_embedding)
                        # Normalize to [0, 1] range (cosine similarity is [-1, 1])
                        normalized = (similarity + 1.0) / 2.0
                        best_vector_score = max(best_vector_score, normalized)
                
                ann_results.append({
                    "embedding_id": chunk_id,
                    "score": best_vector_score,
                    "chunk_id": chunk_id,
                    "file_id": file_id,
                    "file_path": file_path,
                    "chunk_text": chunk_text,
                    "source_id": source_id,
                    "project_id": project_id,
                    "filetype": filetype,
                    "chunk_index": chunk_index,
                    "start_char": start_char,
                    "end_char": end_char,
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "message_uuid": message_uuid,
                })
        
        # Build results from ANN results, FILTERING BY PROJECT_ID AND EXCLUDED CHAT_IDS
        results = []
        excluded_chat_ids_set = set(request.exclude_chat_ids) if request.exclude_chat_ids else set()
        for result in ann_results:
            # CRITICAL: Filter by project_id to ensure strict isolation
            if result.get("project_id") != request.project_id:
                logger.warning(f"[ISOLATION] Filtered out result with wrong project_id: {result.get('project_id')} (expected {request.project_id})")
                continue
            
            # CRITICAL: Filter out trashed chats
            chat_id = result.get("chat_id")
            if chat_id and chat_id in excluded_chat_ids_set:
                logger.debug(f"[TRASH-FILTER] Filtered out result from trashed chat_id: {chat_id}")
                continue
            
            source_type = "chat" if result.get("chat_id") is not None else "file"
            results.append(SearchResult(
                score=float(result["score"]),
                project_id=result["project_id"],
                source_id=result["source_id"],
                file_path=result.get("file_path"),
                filetype=result.get("filetype") or (Path(result.get("file_path")).suffix.lstrip('.') if result.get("file_path") else None),
                chunk_index=result["chunk_index"],
                text=result["chunk_text"],
                start_char=result["start_char"],
                end_char=result["end_char"],
                source_type=source_type,
                chat_id=result.get("chat_id"),
                message_id=result.get("message_id"),
                message_uuid=result.get("message_uuid")
            ))
            
            # Stop once we have enough results
            if len(results) >= request.limit:
                break
        
        logger.info(f"[MEMORY-QUERY] Returning {len(results)} results for project_id={request.project_id}")
        return SearchResponse(results=results)
        
    except Exception as e:
        logger.error(f"Error searching: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/chats/{project_id}/{chat_id}")
async def delete_chat_messages(project_id: str, chat_id: str):
    """
    Delete all chat messages for a specific chat_id from memory_service.
    This is called when a chat is permanently deleted.
    """
    try:
        deleted_count = db.delete_chat_messages_by_chat_id(project_id, chat_id)
        return {
            "status": "ok",
            "message": f"Deleted {deleted_count} chat messages for chat_id={chat_id}",
            "deleted_count": deleted_count
        }
    except Exception as e:
        logger.error(f"Failed to delete chat messages: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/index-chat-message")
async def index_chat_message_endpoint(request: IndexChatMessageRequest):
    """
    Enqueue a chat message for async indexing.
    
    This endpoint is called by the Backend Server after saving a message.
    It enqueues the message for background indexing and returns immediately.
    Indexing happens asynchronously via worker threads.
    
    Returns:
        - job_id: Unique job identifier
        - message_uuid: Message UUID (if available immediately, otherwise None)
        - status: "queued" if successfully enqueued, "error" if enqueue failed
    """
    try:
        # Parse timestamp
        timestamp = datetime.fromisoformat(request.timestamp.replace('Z', '+00:00'))
        
        # Create message_uuid early (before enqueueing) for fact exclusion
        # This is a lightweight operation that just upserts the message record
        source_id = f"project-{request.project_id}"
        db.init_db(source_id, project_id=request.project_id)
        db.upsert_source(source_id, request.project_id, "", None, None)
        chat_message_id = db.upsert_chat_message(
            source_id=source_id,
            project_id=request.project_id,
            chat_id=request.chat_id,
            message_id=request.message_id,
            role=request.role,
            content=request.content,
            timestamp=timestamp,
            message_index=request.message_index
        )
        chat_message = db.get_chat_message_by_id(chat_message_id, source_id)
        message_uuid = chat_message.message_uuid if chat_message else None
        
        # Enqueue job for async processing (with message_uuid for fact exclusion)
        indexing_queue = get_indexing_queue()
        job_id, success = indexing_queue.enqueue(
            project_id=request.project_id,
            chat_id=request.chat_id,
            message_id=request.message_id,
            role=request.role,
            content=request.content,
            timestamp=timestamp,
            message_index=request.message_index,
            message_uuid=message_uuid  # Pass message_uuid to job
        )
        
        if success:
            logger.info(f"[MEMORY] Enqueued indexing job {job_id} for chat_id={request.chat_id} project_id={request.project_id}, message_uuid={message_uuid}")
            return {
                "status": "queued",
                "message": "Indexing job enqueued successfully",
                "job_id": job_id,
                "message_uuid": message_uuid  # Available immediately for fact exclusion
            }
        else:
            logger.warning(f"[MEMORY] Failed to enqueue indexing job for chat_id={request.chat_id} project_id={request.project_id}")
            return {
                "status": "error",
                "message": "Failed to enqueue indexing job",
                "job_id": None,
                "message_uuid": message_uuid  # Still return message_uuid even if enqueue failed
            }
            
    except Exception as e:
        logger.error(f"Error enqueueing indexing job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/index-job-status/{job_id}")
async def get_index_job_status(job_id: str):
    """
    Get the status of an indexing job.
    
    Returns job state, timing, and completion status for tooltip display.
    """
    try:
        indexing_queue = get_indexing_queue()
        job_status = indexing_queue.get_job_status(job_id)
        
        if not job_status:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        return job_status
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class SearchFactsRequest(BaseModel):
    project_id: str
    query: str
    limit: int = 10
    exclude_message_uuid: Optional[str] = None  # Exclude facts from this message UUID (prevents counting facts just stored)


class FactResponse(BaseModel):
    fact_id: str
    project_id: str
    fact_key: str
    value_text: str
    value_type: str
    confidence: float
    source_message_uuid: str
    created_at: str
    effective_at: str
    supersedes_fact_id: Optional[str] = None
    is_current: bool


class SearchFactsResponse(BaseModel):
    facts: List[FactResponse]


@app.post("/search-facts", response_model=SearchFactsResponse)
async def search_facts(request: SearchFactsRequest):
    """
    Search current facts for a project.
    
    Returns facts matching the query in fact_key or value_text.
    Only returns current facts (is_current=1).
    
    Facts DB contract: project_id must be UUID, never project name/slug.
    """
    try:
        # Enforce Facts DB contract: project_id must be UUID
        from server.services.projects.project_resolver import validate_project_uuid
        validate_project_uuid(request.project_id)
        
        source_id = f"project-{request.project_id}"
        logger.info(f"[FACTS-API] Searching facts for project_id={request.project_id}, query='{request.query}', source_id={source_id}, exclude_message_uuid={request.exclude_message_uuid}")
        facts = db.search_current_facts(
            project_id=request.project_id,
            query=request.query,
            limit=request.limit,
            source_id=source_id,
            exclude_message_uuid=request.exclude_message_uuid  # Exclude facts from current message
        )
        logger.info(f"[FACTS-API] Found {len(facts)} facts for query '{request.query}'")
        
        fact_responses = [
            FactResponse(
                fact_id=fact["fact_id"],
                project_id=fact["project_id"],
                fact_key=fact["fact_key"],
                value_text=fact["value_text"],
                value_type=fact["value_type"],
                confidence=fact["confidence"],
                source_message_uuid=fact["source_message_uuid"],
                created_at=fact["created_at"].isoformat() if isinstance(fact["created_at"], datetime) else str(fact["created_at"]),
                effective_at=fact["effective_at"].isoformat() if isinstance(fact["effective_at"], datetime) else str(fact["effective_at"]),
                supersedes_fact_id=fact.get("supersedes_fact_id"),
                is_current=fact["is_current"]
            )
            for fact in facts
        ]
        
        return SearchFactsResponse(facts=fact_responses)
    except Exception as e:
        logger.error(f"Error searching facts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sources/{source_id}/chunk-stats")
async def get_chunk_stats(source_id: str):
    """
    Get chunking quality statistics for a source.
    Useful for diagnosing indexing quality.
    """
    try:
        # Initialize DB for this source
        db.init_db(source_id)
        conn = db.get_db_connection(source_id)
        cursor = conn.cursor()
        
        # Get total chunks and unique chunks
        cursor.execute("""
            SELECT 
                COUNT(*) as total_chunks,
                COUNT(DISTINCT text) as unique_chunks,
                AVG(LENGTH(text)) as avg_chunk_size,
                MIN(LENGTH(text)) as min_chunk_size,
                MAX(LENGTH(text)) as max_chunk_size,
                COUNT(DISTINCT file_id) as total_files
            FROM chunks
        """)
        stats = cursor.fetchone()
        
        # Get chunk size distribution
        cursor.execute("""
            SELECT 
                CASE 
                    WHEN LENGTH(text) < 100 THEN '< 100'
                    WHEN LENGTH(text) < 500 THEN '100-500'
                    WHEN LENGTH(text) < 1000 THEN '500-1000'
                    WHEN LENGTH(text) < 2000 THEN '1000-2000'
                    ELSE '2000+'
                END as size_range,
                COUNT(*) as count
            FROM chunks
            GROUP BY size_range
            ORDER BY 
                CASE size_range
                    WHEN '< 100' THEN 1
                    WHEN '100-500' THEN 2
                    WHEN '500-1000' THEN 3
                    WHEN '1000-2000' THEN 4
                    ELSE 5
                END
        """)
        size_dist = [{"range": row[0], "count": row[1]} for row in cursor.fetchall()]
        
        conn.close()
        
        return {
            "source_id": source_id,
            "total_chunks": stats[0],
            "unique_chunks": stats[1],
            "duplicate_rate": round((1 - stats[1] / stats[0]) * 100, 2) if stats[0] > 0 else 0,
            "avg_chunk_size": round(stats[2], 1) if stats[2] else 0,
            "min_chunk_size": stats[3] or 0,
            "max_chunk_size": stats[4] or 0,
            "total_files": stats[5] or 0,
            "size_distribution": size_dist
        }
    except Exception as e:
        logger.error(f"Error getting chunk stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/filetree/{source_id}", response_model=FileTreeResponse)
async def get_filetree(
    source_id: str,
    path: str = Query("", description="Relative path from source root (directory or file)"),
    max_depth: int = Query(2, ge=0, le=10, description="Maximum depth to traverse (0 = root only)"),
    max_entries: int = Query(500, ge=1, le=5000, description="Maximum total entries to include"),
):
    """
    List the directory tree for a Memory Source.
    
    Returns a tree structure starting at the specified path (relative to source root).
    - If path is empty, starts at source root
    - If path is a directory, lists its contents
    - If path is a file, returns a single node for that file
    
    Safety:
    - All paths are validated to prevent directory traversal (../ escapes)
    - Operations are bounded by max_depth, max_entries
    - Read-only (no write/delete/rename operations)
    """
    try:
        return filetree_manager.list_tree(
            source_id=source_id,
            rel_path=path,
            max_depth=max_depth,
            max_entries=max_entries,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing filetree for source {source_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/filetree/{source_id}/file", response_model=FileReadResponse)
async def read_file(
    source_id: str,
    path: str = Query(..., description="Relative file path from source root"),
    max_bytes: int = Query(65536, ge=1, le=5_000_000, description="Maximum bytes to read (default: 64KB)"),
):
    """
    Read a single file from a Memory Source.
    
    Returns file content with encoding detection and binary file detection.
    - Attempts UTF-8 decoding with error replacement
    - Detects binary files (null bytes or high replacement character ratio)
    - Enforces max_bytes limit and sets truncated flag
    
    Safety:
    - Path is validated to prevent directory traversal (../ escapes)
    - Strictly confined to source root directory
    - Read-only (no write/delete operations)
    """
    try:
        return filetree_manager.read_file(
            source_id=source_id,
            rel_path=path,
            max_bytes=max_bytes,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading file from source {source_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Facts API Endpoints
# ============================================================================

# REMOVED: All NEW facts table system endpoints
# - /facts/store - use fact_extractor → store_project_fact instead
# - /facts/get - use /search-facts endpoint instead
# - /facts/get-by-rank - use /search-facts and filter by fact_key instead
# - /facts/get-single - use get_current_fact() or /search-facts instead
# All fact operations now use project_facts table via fact_extractor and /search-facts


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)

