"""
In-memory vector cache for query embeddings.

Caches query embeddings to avoid recomputing embeddings for identical queries.
This cache is per-process and only caches query embeddings (not document embeddings).
"""
import logging
import re
from typing import Tuple
import numpy as np

from memory_service.config import EMBEDDING_MODEL
from memory_service.embeddings import embed_query as _embed_query_uncached

logger = logging.getLogger(__name__)

# Maximum cache size (number of unique query embeddings to cache)
MAX_CACHE_SIZE = 512


def _normalize_query(query: str) -> str:
    """
    Normalize a query string for cache key generation.
    
    - Strips leading/trailing whitespace
    - Converts to lowercase
    - Collapses multiple whitespace characters into single spaces
    
    Args:
        query: Raw query string
        
    Returns:
        Normalized query string
    """
    if not query:
        return ""
    # Strip, lowercase, and collapse whitespace
    normalized = query.strip().lower()
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized


# Internal cache: maps (normalized_query, model_name) -> embedding
# Using a dict with manual LRU eviction since numpy arrays aren't hashable for lru_cache
_cache_dict: dict[Tuple[str, str], np.ndarray] = {}
_cache_order: list[Tuple[str, str]] = []  # Track insertion order for LRU eviction


def _get_cached_embedding(key: Tuple[str, str]) -> np.ndarray | None:
    """
    Get embedding from cache if it exists.
    Updates LRU order (moves to end = most recently used).
    
    Args:
        key: Cache key (normalized_query, model_name)
        
    Returns:
        Cached embedding array, or None if not found
    """
    if key in _cache_dict:
        # Move to end (most recently used)
        if key in _cache_order:
            _cache_order.remove(key)
        _cache_order.append(key)
        return _cache_dict[key]
    return None


def _set_cached_embedding(key: Tuple[str, str], embedding: np.ndarray) -> None:
    """
    Store embedding in cache, evicting oldest entry if cache is full.
    
    Args:
        key: Cache key (normalized_query, model_name)
        embedding: Embedding array to cache
    """
    # If key already exists, just update order
    if key in _cache_dict:
        if key in _cache_order:
            _cache_order.remove(key)
        _cache_order.append(key)
        _cache_dict[key] = embedding
        return
    
    # If cache is full, evict oldest (first in order)
    if len(_cache_dict) >= MAX_CACHE_SIZE:
        oldest_key = _cache_order.pop(0)
        del _cache_dict[oldest_key]
    
    # Add new entry
    _cache_dict[key] = embedding
    _cache_order.append(key)


def get_query_embedding(query: str) -> np.ndarray:
    """
    Return the embedding for a query string, using an in-memory cache.
    
    Query strings are normalized (lowercase, whitespace collapsed) before
    caching, so queries like "Hello World" and "hello  world" will use
    the same cached embedding.
    
    Args:
        query: Query text string
        
    Returns:
        numpy array of shape [1024] containing the query embedding
    """
    # Normalize query and build cache key
    normalized = _normalize_query(query)
    cache_key = (normalized, EMBEDDING_MODEL)
    
    # Check cache
    cached = _get_cached_embedding(cache_key)
    if cached is not None:
        logger.info("[CACHE] Query embedding cache HIT (model=%s)", EMBEDDING_MODEL)
        return cached
    
    # Cache miss - compute embedding
    logger.info("[CACHE] Query embedding cache MISS (model=%s)", EMBEDDING_MODEL)
    embedding = _embed_query_uncached(query)
    
    # Store in cache
    _set_cached_embedding(cache_key, embedding)
    
    return embedding


def clear_query_embedding_cache() -> None:
    """
    Clear the in-memory query embedding cache.
    
    Useful for testing or if you need to free memory.
    """
    global _cache_dict, _cache_order
    _cache_dict.clear()
    _cache_order.clear()
    logger.info("[CACHE] Query embedding cache cleared")


def get_cache_stats() -> dict:
    """
    Get statistics about the current cache state.
    
    Returns:
        Dictionary with cache size and max size
    """
    return {
        "size": len(_cache_dict),
        "max_size": MAX_CACHE_SIZE
    }

