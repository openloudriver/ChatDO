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

from memory_service.config import API_HOST, API_PORT, EMBEDDING_MODEL
from memory_service.store import db
from memory_service.indexer import index_source
from memory_service.watcher import WatcherManager
from memory_service.embeddings import embed_query

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global watcher manager
watcher_manager = WatcherManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup
    logger.info("Initializing Memory Service...")
    db.init_db()
    logger.info("Database initialized")
    
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
    """Get list of configured sources."""
    from memory_service.config import load_sources
    sources = load_sources()
    
    return {
        "sources": [
            {
                "id": s.id,
                "project_id": s.project_id,
                "root_path": str(s.root_path),
                "include_glob": s.include_glob,
                "exclude_glob": s.exclude_glob
            }
            for s in sources
        ]
    }


@app.post("/reindex")
async def reindex(request: ReindexRequest):
    """Trigger a full reindex of a source."""
    try:
        count = index_source(request.source_id)
        return {"status": "ok", "files_indexed": count}
    except Exception as e:
        logger.error(f"Error reindexing source {request.source_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest):
    """
    Search for relevant chunks by project_id and query.
    
    Returns top-N matches ordered by cosine similarity.
    """
    try:
        # Embed the query
        query_embedding = embed_query(request.query)
        
        # Get all embeddings for this project
        all_embeddings = db.get_all_embeddings_for_project(request.project_id, EMBEDDING_MODEL)
        
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

