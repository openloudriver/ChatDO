"""
Embedding generation using sentence-transformers.

Loads the all-MiniLM-L6-v2 model and provides batched embedding generation.
"""
import numpy as np
from sentence_transformers import SentenceTransformer
from typing import List
import logging

from memory_service.config import EMBEDDING_MODEL

logger = logging.getLogger(__name__)

# Global model instance (loaded once at startup)
_model: SentenceTransformer = None


def get_model() -> SentenceTransformer:
    """Get or load the embedding model."""
    global _model
    if _model is None:
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
        _model = SentenceTransformer(EMBEDDING_MODEL)
        logger.info("Embedding model loaded successfully")
    return _model


def embed_texts(texts: List[str]) -> np.ndarray:
    """
    Generate embeddings for a list of texts.
    
    Args:
        texts: List of text strings to embed
        
    Returns:
        numpy array of shape [N, 384] where N is the number of texts
    """
    if not texts:
        return np.array([])
    
    model = get_model()
    embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return embeddings


def embed_query(query: str) -> np.ndarray:
    """
    Generate embedding for a single query string.
    
    Args:
        query: Query text string
        
    Returns:
        numpy array of shape [384]
    """
    return embed_texts([query])[0]

