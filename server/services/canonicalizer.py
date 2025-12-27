"""
Canonicalizer Subsystem for Facts.

This is the authoritative canonicalization layer that converts raw topics
from Nano router into canonical topics using:
1. Alias Table (authoritative mappings)
2. Embedding similarity (BGE model)
3. Teacher Model (GPT-5 for low-confidence cases)

The canonicalizer is used on both Facts write and Facts read paths.
"""
import logging
import numpy as np
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Confidence threshold for embedding similarity
EMBEDDING_SIMILARITY_THRESHOLD = 0.92

# Import embedding utilities (reuse Memory Service embedding model)
try:
    import sys
    from pathlib import Path
    # Add memory_service to path if needed
    memory_service_path = Path(__file__).parent.parent.parent / "memory_service"
    if str(memory_service_path) not in sys.path:
        sys.path.insert(0, str(memory_service_path))
    from embeddings import embed_query, get_model
    from config import EMBEDDING_MODEL, EMBEDDING_DIM
    _EMBEDDING_AVAILABLE = True
except ImportError as e:
    logger.warning(f"[CANONICALIZER] Could not import embedding utilities: {e}")
    embed_query = None
    get_model = None
    EMBEDDING_MODEL = None
    EMBEDDING_DIM = None
    _EMBEDDING_AVAILABLE = False

# Import alias table
from server.services.alias_table import AliasTable, AliasEntry


@dataclass
class CanonicalizationResult:
    """Result of canonicalization process."""
    canonical_topic: str
    confidence: float  # 0.0 to 1.0
    source: str  # "alias_table" | "embedding" | "teacher" | "fallback"
    teacher_invoked: bool
    raw_topic: str
    aliases_used: Optional[list] = None  # List of aliases that matched


class Canonicalizer:
    """
    Canonicalizer subsystem for topic normalization.
    
    This subsystem provides deterministic canonicalization using:
    1. Alias Table (authoritative mappings)
    2. Embedding similarity (BGE model)
    3. Teacher Model (GPT-5 for low-confidence cases)
    """
    
    def __init__(self):
        """Initialize the canonicalizer."""
        self.alias_table = AliasTable()
        self._embedding_model_available = _EMBEDDING_AVAILABLE and embed_query is not None
        
        if not self._embedding_model_available:
            logger.warning("[CANONICALIZER] Embedding model not available - will use alias table only")
    
    def normalize_string(self, raw: str) -> str:
        """
        Basic string normalization (lowercase, strip, remove "my/favorite").
        
        This is the first step before checking alias table or embeddings.
        """
        if not raw:
            return ""
        
        # Lowercase and strip
        normalized = raw.lower().strip()
        
        # Remove "favorite(s)" prefix if present
        import re
        normalized = re.sub(r'\bfavorites?\s*[-_\s]*', '', normalized, flags=re.IGNORECASE)
        normalized = normalized.strip()
        
        # Remove "my" prefix if present
        normalized = re.sub(r'^my\s*[-_\s]*', '', normalized, flags=re.IGNORECASE)
        normalized = normalized.strip()
        
        return normalized
    
    def canonicalize(
        self,
        raw_topic: str,
        invoke_teacher: bool = True
    ) -> CanonicalizationResult:
        """
        Canonicalize a raw topic to a canonical topic.
        
        Process:
        1. Normalize string (basic cleanup)
        2. Check Alias Table (exact or mapped alias)
        3. If not found, use embedding similarity
        4. If similarity < threshold, invoke Teacher (if enabled)
        
        Args:
            raw_topic: Raw topic string from Nano router
            invoke_teacher: Whether to invoke teacher for low-confidence cases
            
        Returns:
            CanonicalizationResult with canonical topic, confidence, and source
        """
        if not raw_topic:
            return CanonicalizationResult(
                canonical_topic="unknown",
                confidence=0.0,
                source="fallback",
                teacher_invoked=False,
                raw_topic=raw_topic
            )
        
        # Step 1: Normalize string
        normalized = self.normalize_string(raw_topic)
        
        if not normalized:
            return CanonicalizationResult(
                canonical_topic="unknown",
                confidence=0.0,
                source="fallback",
                teacher_invoked=False,
                raw_topic=raw_topic
            )
        
        # Step 2: Check Alias Table (authoritative)
        alias_result = self.alias_table.find_canonical(normalized)
        if alias_result:
            logger.debug(
                f"[CANONICALIZER] Alias table match: '{raw_topic}' → '{alias_result.canonical_topic}' "
                f"(via alias: {alias_result.matched_alias})"
            )
            return CanonicalizationResult(
                canonical_topic=alias_result.canonical_topic,
                confidence=1.0,
                source="alias_table",
                teacher_invoked=False,
                raw_topic=raw_topic,
                aliases_used=[alias_result.matched_alias] if alias_result.matched_alias else None
            )
        
        # Step 3: Embedding similarity check
        if self._embedding_model_available:
            embedding_result = self._canonicalize_via_embedding(normalized)
            if embedding_result and embedding_result.confidence >= EMBEDDING_SIMILARITY_THRESHOLD:
                logger.debug(
                    f"[CANONICALIZER] Embedding match: '{raw_topic}' → '{embedding_result.canonical_topic}' "
                    f"(confidence: {embedding_result.confidence:.3f})"
                )
                return embedding_result
            
            # Step 4: Low confidence - invoke Teacher if enabled
            if invoke_teacher and embedding_result and embedding_result.confidence < EMBEDDING_SIMILARITY_THRESHOLD:
                teacher_result = self._canonicalize_via_teacher(raw_topic, normalized)
                if teacher_result:
                    return teacher_result
        
        # Fallback: use normalized string as canonical (low confidence)
        logger.warning(
            f"[CANONICALIZER] No canonical match found for '{raw_topic}', using normalized fallback"
        )
        return CanonicalizationResult(
            canonical_topic=normalized,
            confidence=0.5,  # Low confidence fallback
            source="fallback",
            teacher_invoked=False,
            raw_topic=raw_topic
        )
    
    def _canonicalize_via_embedding(
        self,
        normalized_topic: str
    ) -> Optional[CanonicalizationResult]:
        """
        Canonicalize using embedding similarity against existing canonical topics.
        
        Args:
            normalized_topic: Normalized topic string
            
        Returns:
            CanonicalizationResult if similarity >= threshold, None otherwise
        """
        if not self._embedding_model_available:
            return None
        
        try:
            # Embed the normalized topic
            topic_embedding = embed_query(normalized_topic)
            
            # Get all canonical topics with their embeddings from alias table
            canonical_topics = self.alias_table.get_all_canonical_topics()
            
            if not canonical_topics:
                # No canonical topics exist yet - cannot match
                return None
            
            # Find best match via cosine similarity
            best_match = None
            best_similarity = 0.0
            
            for canonical_topic, canonical_embedding in canonical_topics:
                if canonical_embedding is None:
                    continue
                
                # Compute cosine similarity
                dot_product = np.dot(topic_embedding, canonical_embedding)
                norm_topic = np.linalg.norm(topic_embedding)
                norm_canonical = np.linalg.norm(canonical_embedding)
                
                if norm_topic > 0 and norm_canonical > 0:
                    similarity = dot_product / (norm_topic * norm_canonical)
                    # Normalize to [0, 1] range (cosine similarity is [-1, 1])
                    normalized_similarity = (similarity + 1.0) / 2.0
                    
                    if normalized_similarity > best_similarity:
                        best_similarity = normalized_similarity
                        best_match = canonical_topic
            
            if best_match and best_similarity >= EMBEDDING_SIMILARITY_THRESHOLD:
                return CanonicalizationResult(
                    canonical_topic=best_match,
                    confidence=best_similarity,
                    source="embedding",
                    teacher_invoked=False,
                    raw_topic=normalized_topic
                )
            
            # Return result even if below threshold (for teacher invocation)
            if best_match:
                return CanonicalizationResult(
                    canonical_topic=best_match,
                    confidence=best_similarity,
                    source="embedding",
                    teacher_invoked=False,
                    raw_topic=normalized_topic
                )
            
            return None
            
        except Exception as e:
            logger.error(f"[CANONICALIZER] Error in embedding canonicalization: {e}", exc_info=True)
            return None
    
    def _canonicalize_via_teacher(
        self,
        raw_topic: str,
        normalized_topic: str
    ) -> Optional[CanonicalizationResult]:
        """
        Invoke Teacher Model (GPT-5) for high-accuracy canonicalization.
        
        Teacher decides:
        - Canonical topic name
        - Alias mappings to add to Alias Table
        
        Args:
            raw_topic: Original raw topic from Nano
            normalized_topic: Normalized topic string
            
        Returns:
            CanonicalizationResult with teacher's decision
        """
        from server.services.teacher_model import invoke_teacher_for_canonicalization
        
        try:
            logger.info(
                f"[CANONICALIZER] Invoking Teacher Model for low-confidence topic: '{raw_topic}'"
            )
            
            teacher_result = invoke_teacher_for_canonicalization(raw_topic, normalized_topic)
            
            if teacher_result:
                # Teacher has decided canonical topic and aliases
                # Generate embedding for canonical topic if embedding model is available
                canonical_embedding = None
                if self._embedding_model_available:
                    try:
                        canonical_embedding = embed_query(teacher_result.canonical_topic)
                    except Exception as e:
                        logger.warning(f"[CANONICALIZER] Failed to generate embedding for canonical topic: {e}")
                
                # Update alias table with teacher's mappings
                self.alias_table.add_entry(
                    canonical_topic=teacher_result.canonical_topic,
                    aliases=teacher_result.aliases,
                    embedding=canonical_embedding,
                    created_by="teacher",
                    confidence=1.0
                )
                
                logger.info(
                    f"[CANONICALIZER] Teacher canonicalized '{raw_topic}' → '{teacher_result.canonical_topic}' "
                    f"with {len(teacher_result.aliases)} aliases"
                )
                
                return CanonicalizationResult(
                    canonical_topic=teacher_result.canonical_topic,
                    confidence=1.0,
                    source="teacher",
                    teacher_invoked=True,
                    raw_topic=raw_topic,
                    aliases_used=teacher_result.aliases
                )
            
            return None
            
        except Exception as e:
            logger.error(f"[CANONICALIZER] Error invoking teacher: {e}", exc_info=True)
            return None


# Global canonicalizer instance
_canonicalizer: Optional[Canonicalizer] = None


def get_canonicalizer() -> Canonicalizer:
    """Get or create the global canonicalizer instance."""
    global _canonicalizer
    if _canonicalizer is None:
        _canonicalizer = Canonicalizer()
    return _canonicalizer


def canonicalize_topic(
    raw_topic: str,
    invoke_teacher: bool = True
) -> CanonicalizationResult:
    """
    Canonicalize a raw topic using the canonicalizer subsystem.
    
    This is the main entry point for canonicalization.
    
    Args:
        raw_topic: Raw topic string from Nano router
        invoke_teacher: Whether to invoke teacher for low-confidence cases
        
    Returns:
        CanonicalizationResult with canonical topic, confidence, and metadata
    """
    canonicalizer = get_canonicalizer()
    return canonicalizer.canonicalize(raw_topic, invoke_teacher=invoke_teacher)

