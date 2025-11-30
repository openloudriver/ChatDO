"""
HTTP interface for ChatDO → Memory Service communication.

Provides REST API endpoints for health checks, source management, indexing, and search.
"""
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import numpy as np
from contextlib import asynccontextmanager
import asyncio
import threading

from memory_service.config import API_HOST, API_PORT, EMBEDDING_MODEL, load_sources, create_dynamic_source, BASE_DIR, BASE_STORE_PATH, DYNAMIC_SOURCES_PATH, MEMORY_SOURCES_YAML, load_dynamic_sources, save_dynamic_sources, load_static_sources
from memory_service.store import db
from memory_service.indexer import index_source
from memory_service.watcher import WatcherManager
from memory_service.embeddings import embed_query
from memory_service.models import SourceStatus, IndexJob
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global watcher manager
watcher_manager = WatcherManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup
    logger.info("Initializing Memory Service...")
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
    
    # Load sources from config and start watchers
    watcher_manager.start_all()
    logger.info("File watchers started")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Memory Service...")
    watcher_manager.stop_all()
    logger.info("File watchers stopped")


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
    project_id: Optional[str] = "scratch"


class SearchRequest(BaseModel):
    project_id: str
    query: str
    limit: int = 10
    source_ids: Optional[List[str]] = None


class SearchResult(BaseModel):
    score: float
    project_id: str
    source_id: str
    file_path: str
    filetype: str
    chunk_index: int
    text: str
    start_char: int
    end_char: int


class SearchResponse(BaseModel):
    results: List[SearchResult]


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
            project_id=request.project_id or "scratch",
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
                temp_path = projects_path.with_suffix('.json.tmp')
                with open(temp_path, 'w') as pf:
                    json.dump(projects, pf, indent=2)
                temp_path.replace(projects_path)
                logger.info(f"Removed {source_id} from project connections")
    except Exception as e:
        logger.warning(f"Could not update projects.json: {e}")
    
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
    source_dir = BASE_STORE_PATH / source_id
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
    try:
        # Load source config from YAML
        sources = load_sources()
        source_config = None
        for s in sources:
            if s.id == request.source_id:
                source_config = s
                break
        
        if not source_config:
            raise HTTPException(status_code=404, detail=f"Source not found in config: {request.source_id}")
        
        # Delete the old index directory for this source
        import shutil
        from memory_service.config import BASE_STORE_PATH
        source_dir = BASE_STORE_PATH / request.source_id
        if source_dir.exists():
            shutil.rmtree(source_dir, ignore_errors=True)
            logger.info(f"Deleted old index directory for source: {request.source_id}")
        
        # Recreate empty directory
        source_dir.mkdir(parents=True, exist_ok=True)
        
        # Register source in database before indexing
        db_id = db.upsert_source(
            source_config.id,
            source_config.project_id,
            str(source_config.root_path),
            source_config.include_glob,
            source_config.exclude_glob
        )
        logger.info(f"Registered source {request.source_id} in database (db_id: {db_id})")
        
        # Run indexing in background thread to avoid blocking the API
        def run_indexing():
            try:
                index_source(request.source_id)
            except Exception as e:
                logger.error(f"Background indexing failed for {request.source_id}: {e}", exc_info=True)
                db.update_source_stats(
                    request.source_id,
                    status="error",
                    last_error=str(e)
                )
        
        thread = threading.Thread(target=run_indexing, daemon=True)
        thread.start()
        
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
    """
    try:
        # Require source_ids
        if not request.source_ids:
            return SearchResponse(results=[])
        
        # Query expansion: extract key terms and search for them individually
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
        
        # Embed all query variations
        query_embeddings = [embed_query(q) for q in all_queries]
        
        # Search across all specified sources
        all_embeddings = []
        for source_id in request.source_ids:
            try:
                source_embeddings = db.get_all_embeddings_for_source(source_id, EMBEDDING_MODEL)
                all_embeddings.extend(source_embeddings)
            except Exception as e:
                logger.warning(f"Error searching source {source_id}: {e}")
                continue
        
        if not all_embeddings:
            return SearchResponse(results=[])
        
        # Compute cosine similarities using best match across all query variations
        similarities = []
        for chunk_id, embedding, file_id, file_path, chunk_text, source_id, project_id, filetype, chunk_index, start_char, end_char in all_embeddings:
            # Try all query embeddings and take the best match
            best_similarity = 0.0
            for query_embedding in query_embeddings:
                dot_product = np.dot(query_embedding, embedding)
                norm_query = np.linalg.norm(query_embedding)
                norm_embedding = np.linalg.norm(embedding)
            
                if norm_query > 0 and norm_embedding > 0:
                    similarity = dot_product / (norm_query * norm_embedding)
                    best_similarity = max(best_similarity, similarity)
            
            similarities.append((
                best_similarity,
                project_id,
                source_id,
                file_path,
                filetype,
                chunk_index,
                chunk_text,
                start_char,
                end_char
            ))
        
        # Sort by similarity (descending) and take top N
        similarities.sort(key=lambda x: x[0], reverse=True)
        top_results = similarities[:request.limit]
        
        # Build results
        results = []
        for score, project_id, source_id, file_path, filetype, chunk_index, chunk_text, start_char, end_char in top_results:
            results.append(SearchResult(
                score=float(score),
                project_id=project_id,
                source_id=source_id,
                file_path=file_path,
                filetype=filetype or Path(file_path).suffix.lstrip('.'),
                chunk_index=chunk_index,
                text=chunk_text,
                start_char=start_char,
                end_char=end_char
            ))
        
        return SearchResponse(results=results)
        
    except Exception as e:
        logger.error(f"Error searching: {e}", exc_info=True)
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)

