"""
FAISS/HNSW Approximate Nearest Neighbor (ANN) index manager for Memory Service.

Provides fast vector similarity search using FAISS HNSW index with L2-normalized vectors
and inner product metric (equivalent to cosine similarity).
"""
import logging
import numpy as np
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict

logger = logging.getLogger(__name__)

# Try to import FAISS
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    logger.warning("FAISS not available. Install with: pip install faiss-cpu")


class AnnIndexManager:
    """
    Manages FAISS HNSW index for approximate nearest neighbor search.
    
    All vectors are L2-normalized before insertion/search to enable cosine similarity
    via inner product metric.
    """
    
    def __init__(self, dimension: int = 1024):
        """
        Initialize the ANN index manager.
        
        Args:
            dimension: Embedding dimension (default: 1024 for BGE-large-en-v1.5)
        """
        self.dimension = dimension
        
        self.index: Optional[Any] = None  # FAISS index
        self.metadata: Dict[int, Dict[str, Any]] = {}  # Maps FAISS ID -> embedding metadata
        self.embedding_id_to_faiss_id: Dict[int, int] = {}  # Maps embedding_id -> FAISS ID
        self.next_faiss_id = 0  # Counter for FAISS IDs
        self.active_embeddings: set = set()  # Set of active FAISS IDs (for soft deletion)
        
        if not FAISS_AVAILABLE:
            logger.error("[ANN] FAISS not available. ANN search will not work.")
            return
        
        try:
            # Use IndexFlatIP (brute-force inner product) instead of HNSW
            # This is simpler, more stable, and still much faster than pure Python
            # Inner product on L2-normalized vectors = cosine similarity
            self.index = faiss.IndexFlatIP(dimension)
            
            logger.info(f"[ANN] Initialized FAISS IndexFlatIP (dim={dimension}, metric=inner_product)")
        except Exception as e:
            logger.error(f"[ANN] Failed to initialize FAISS index: {e}", exc_info=True)
            self.index = None
    
    def _normalize_vector(self, vector: np.ndarray) -> np.ndarray:
        """
        L2-normalize a vector.
        
        Args:
            vector: Input vector (1D or 2D array)
            
        Returns:
            L2-normalized vector (same shape)
        """
        if vector.ndim == 1:
            norm = np.linalg.norm(vector)
            if norm > 0:
                return vector / norm
            return vector
        else:
            # Normalize each row
            norms = np.linalg.norm(vector, axis=1, keepdims=True)
            norms = np.where(norms > 0, norms, 1.0)  # Avoid division by zero
            return vector / norms
    
    def is_available(self) -> bool:
        """Check if ANN index is available and ready."""
        return FAISS_AVAILABLE and self.index is not None
    
    def add_embeddings(self, vectors: np.ndarray, metadata_list: List[Dict[str, Any]]) -> None:
        """
        Add embeddings to the index.
        
        Args:
            vectors: Embedding vectors, shape [N, D] where D is dimension
            metadata_list: List of metadata dicts, one per vector. Each dict must contain:
                - embedding_id: int (unique embedding ID from database)
                - chunk_id: int
                - file_id: Optional[int]
                - file_path: Optional[str]
                - chunk_text: str
                - source_id: str
                - project_id: str
                - filetype: Optional[str]
                - chunk_index: int
                - start_char: int
                - end_char: int
                - chat_id: Optional[str]
                - message_id: Optional[str]
        """
        if not self.is_available():
            logger.warning("[ANN] Cannot add embeddings: FAISS index not available")
            return
        
        if len(vectors) != len(metadata_list):
            logger.error(f"[ANN] Mismatch: {len(vectors)} vectors but {len(metadata_list)} metadata entries")
            return
        
        if len(vectors) == 0:
            return
        
        try:
            # Ensure vectors are float32 and correct shape
            if vectors.dtype != np.float32:
                vectors = vectors.astype(np.float32)
            
            # Reshape if needed (handle 1D input)
            if vectors.ndim == 1:
                vectors = vectors.reshape(1, -1)
            
            # L2-normalize vectors
            normalized_vectors = self._normalize_vector(vectors)
            
            # Filter valid embeddings and prepare for FAISS
            valid_vectors = []
            valid_metadata_list = []
            for i, (vector, metadata) in enumerate(zip(normalized_vectors, metadata_list)):
                embedding_id = metadata.get("embedding_id")
                if embedding_id is None:
                    logger.warning(f"[ANN] Metadata entry {i} missing embedding_id, skipping")
                    continue
                
                # Check if embedding already exists (update instead of duplicate)
                if embedding_id in self.embedding_id_to_faiss_id:
                    # Remove old entry first
                    old_faiss_id = self.embedding_id_to_faiss_id[embedding_id]
                    self.active_embeddings.discard(old_faiss_id)
                    # Note: FAISS doesn't support removal, so we mark as inactive
                    # The old entry will be filtered out during search
                
                valid_vectors.append(vector)
                valid_metadata_list.append(metadata)
            
            if len(valid_vectors) == 0:
                logger.warning("[ANN] No valid embeddings to add")
                return
            
            # IndexHNSWFlat doesn't support add_with_ids, so we use add() and track sequential IDs
            # FAISS will assign sequential IDs starting from current ntotal
            start_faiss_id = self.index.ntotal
            
            # Validate vectors array before passing to FAISS
            valid_vectors_array = np.array(valid_vectors, dtype=np.float32)
            
            # Additional validation: check for NaN or Inf values that could cause FAISS to crash
            if np.any(np.isnan(valid_vectors_array)) or np.any(np.isinf(valid_vectors_array)):
                logger.error("[ANN] Invalid vectors detected (NaN or Inf), skipping batch")
                return
            
            # Check dimension matches
            if valid_vectors_array.shape[1] != self.dimension:
                logger.error(f"[ANN] Vector dimension mismatch: expected {self.dimension}, got {valid_vectors_array.shape[1]}")
                return
            
            # Add to FAISS index with error handling
            try:
                self.index.add(valid_vectors_array)
            except Exception as e:
                logger.error(f"[ANN] FAISS add() failed: {e}", exc_info=True)
                return
            
            # Map FAISS sequential IDs to our embedding_ids
            for i, metadata in enumerate(valid_metadata_list):
                embedding_id = metadata.get("embedding_id")
                faiss_internal_id = start_faiss_id + i
                
                # Store metadata mapping using FAISS internal ID
                self.metadata[faiss_internal_id] = metadata.copy()
                self.embedding_id_to_faiss_id[embedding_id] = faiss_internal_id
                self.active_embeddings.add(faiss_internal_id)
            
            logger.info(f"[ANN] Added {len(valid_metadata_list)} embeddings to index (total: {self.index.ntotal})")
            
        except Exception as e:
            logger.error(f"[ANN] Error adding embeddings: {e}", exc_info=True)
    
    def remove_embeddings(self, embedding_ids: List[int]) -> None:
        """
        Remove embeddings from the index (soft deletion).
        
        Since FAISS doesn't support efficient removal, we mark embeddings as inactive
        and filter them out during search.
        
        Args:
            embedding_ids: List of embedding IDs to remove
        """
        if not self.is_available():
            logger.warning("[ANN] Cannot remove embeddings: FAISS index not available")
            return
        
        removed_count = 0
        for embedding_id in embedding_ids:
            if embedding_id in self.embedding_id_to_faiss_id:
                faiss_id = self.embedding_id_to_faiss_id[embedding_id]
                if faiss_id in self.active_embeddings:
                    self.active_embeddings.remove(faiss_id)
                    removed_count += 1
                    # Keep metadata for now (in case we need to rebuild)
        
        if removed_count > 0:
            logger.info(f"[ANN] Removed {removed_count} embeddings from index (marked inactive)")
    
    def search(self, query_vector: np.ndarray, top_k: int, filter_source_ids: Optional[List[str]] = None, filter_project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search for nearest neighbors.
        
        Args:
            query_vector: Query embedding vector, shape [D] or [1, D]
            top_k: Number of results to return
            filter_source_ids: Optional list of source_ids to filter results (file sources connected to project)
            filter_project_id: REQUIRED for project isolation
            
        PROJECT ISOLATION:
        - Chat sources (source_id starts with "project-"): Strict project isolation - must match filter_project_id
        - File sources: If source_id is in filter_source_ids (connected to project via projects.json), 
          allow cross-project access. This enables sharing file sources across projects without reindexing.
            
        Returns:
            List of result dicts, each containing:
                - embedding_id: int
                - score: float (inner product, normalized to [0, 1] for cosine similarity)
                - chunk_id: int
                - file_id: Optional[int]
                - file_path: Optional[str]
                - chunk_text: str
                - source_id: str
                - project_id: str
                - filetype: Optional[str]
                - chunk_index: int
                - start_char: int
                - end_char: int
                - chat_id: Optional[str]
                - message_id: Optional[str]
        """
        if not self.is_available():
            logger.warning("[ANN] Cannot search: FAISS index not available")
            return []
        
        if self.index.ntotal == 0:
            return []
        
        try:
            # Ensure query vector is float32 and correct shape
            if query_vector.dtype != np.float32:
                query_vector = query_vector.astype(np.float32)
            
            # Reshape if needed
            if query_vector.ndim == 1:
                query_vector = query_vector.reshape(1, -1)
            
            # L2-normalize query vector
            normalized_query = self._normalize_vector(query_vector)
            
            # Search (request more results to account for filtering)
            search_k = top_k * 3 if filter_source_ids else top_k
            search_k = min(search_k, self.index.ntotal)  # Don't exceed index size
            
            distances, faiss_ids = self.index.search(normalized_query, search_k)
            
            # Process results
            results = []
            for i in range(len(faiss_ids[0])):
                faiss_id = int(faiss_ids[0][i])
                distance = float(distances[0][i])
                
                # Skip inactive embeddings
                if faiss_id not in self.active_embeddings:
                    continue
                
                # Get metadata
                metadata = self.metadata.get(faiss_id)
                if not metadata:
                    continue
                
                source_id = metadata.get("source_id")
                metadata_project_id = metadata.get("project_id")
                
                # Apply source filter if provided
                if filter_source_ids and source_id not in filter_source_ids:
                    # Skip file sources that don't match
                    # BUT: Always include chat embeddings (source_id starts with "project-") for cross-chat memory
                    if not (source_id and source_id.startswith("project-")):
                        continue
                
                # PROJECT ISOLATION LOGIC:
                # - Chat sources (source_id starts with "project-"): Strict project isolation - must match project_id
                # - File sources: If source_id is in filter_source_ids (connected to this project), allow cross-project access
                #   This enables sharing file sources across projects without reindexing
                if filter_project_id:
                    is_chat_source = source_id and source_id.startswith("project-")
                    if is_chat_source:
                        # Chat sources: strict isolation - must match project_id
                        if metadata_project_id != filter_project_id:
                            continue
                    else:
                        # File sources: if source_id is in allowed list, allow it (cross-project access)
                        # If source_id not in filter_source_ids, it was already filtered above
                        # So at this point, if we have a file source, it's allowed regardless of project_id
                        pass
                
                # Convert inner product to normalized cosine similarity [0, 1]
                # Inner product of normalized vectors is in [-1, 1], normalize to [0, 1]
                score = (distance + 1.0) / 2.0
                
                # Build result dict
                result = {
                    "embedding_id": metadata.get("embedding_id"),
                    "score": score,
                    "chunk_id": metadata.get("chunk_id"),
                    "file_id": metadata.get("file_id"),
                    "file_path": metadata.get("file_path"),
                    "chunk_text": metadata.get("chunk_text"),
                    "source_id": metadata.get("source_id"),
                    "project_id": metadata.get("project_id"),
                    "filetype": metadata.get("filetype"),
                    "chunk_index": metadata.get("chunk_index"),
                    "start_char": metadata.get("start_char"),
                    "end_char": metadata.get("end_char"),
                    "chat_id": metadata.get("chat_id"),
                    "message_id": metadata.get("message_id"),
                }
                
                results.append(result)
                
                # Stop if we have enough results
                if len(results) >= top_k:
                    break
            
            return results
            
        except Exception as e:
            logger.error(f"[ANN] Error during search: {e}", exc_info=True)
            return []
    
    def get_index_size(self) -> int:
        """Get the number of vectors in the index."""
        if not self.is_available():
            return 0
        return self.index.ntotal
    
    def get_active_count(self) -> int:
        """Get the number of active (non-deleted) embeddings."""
        return len(self.active_embeddings)
    
    def clear(self) -> None:
        """Clear the entire index (for testing or rebuild)."""
        if not self.is_available():
            return
        
        try:
            # Reset index
            self.index.reset()
            self.metadata.clear()
            self.embedding_id_to_faiss_id.clear()
            self.active_embeddings.clear()
            self.next_faiss_id = 0
            logger.info("[ANN] Cleared index")
        except Exception as e:
            logger.error(f"[ANN] Error clearing index: {e}", exc_info=True)

