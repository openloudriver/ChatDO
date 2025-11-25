"""
HTTP interface for ChatDO → Memory Service communication.

Provides REST API endpoints for health checks, source management, indexing, and search.
"""
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import numpy as np
from contextlib import asynccontextmanager

from memory_service.config import API_HOST, API_PORT, EMBEDDING_MODEL, load_sources
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
    
    # Register all sources from config into tracking DB
    sources = load_sources()
    for source_config in sources:
        db.get_or_create_source(
            source_config.id,
            str(source_config.root_path),
            source_config.id,
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


# Request/Response models
class ReindexRequest(BaseModel):
    source_id: str


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
    
    result = []
    for source, latest_job in sources_with_jobs:
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
            "project_id": source.project_id,
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
        
        # Create index job (index_source will create it, but we need the job_id for response)
        # Actually, index_source creates the job, so we'll get it after
        # For now, trigger reindex in background or get job_id from index_source
        # Let's modify to return job_id - we'll need to refactor index_source slightly
        # For now, create job here and pass it through
        
        # Reindex (this will create the job internally and return job_id)
        count, job_id = index_source(request.source_id)
        
        return {
            "status": "ok",
            "job_id": job_id,
            "source_id": request.source_id,
            "files_indexed": count
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
    """
    try:
        # Require source_ids
        if not request.source_ids:
            return SearchResponse(results=[])
        
        # Embed the query
        query_embedding = embed_query(request.query)
        
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
        
        # Compute cosine similarities
        similarities = []
        for chunk_id, embedding, file_id, file_path, chunk_text, source_id, project_id, filetype, chunk_index, start_char, end_char in all_embeddings:
            # Cosine similarity
            dot_product = np.dot(query_embedding, embedding)
            norm_query = np.linalg.norm(query_embedding)
            norm_embedding = np.linalg.norm(embedding)
            
            if norm_query > 0 and norm_embedding > 0:
                similarity = dot_product / (norm_query * norm_embedding)
            else:
                similarity = 0.0
            
            similarities.append((
                similarity,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)

