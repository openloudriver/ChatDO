"""
Topic extraction utility for ChatDO.

This module provides topic extraction from user queries.
Ranked facts extraction and topic normalization have been merged into fact_extractor.py.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def extract_topic_from_query(query: str) -> Optional[str]:
    """
    Extract topic from a user query for facts retrieval.
    
    Uses fact_extractor's normalize_topic() method for consistency.
    
    Args:
        query: User query text
        
    Returns:
        Canonical topic key or None if no confident match
    """
    try:
        from memory_service.fact_extractor import get_fact_extractor
        extractor = get_fact_extractor()
        # Use the private method that normalizes topics
        return extractor._normalize_topic(query)
    except Exception as e:
        logger.warning(f"Failed to extract topic from query '{query}': {e}")
        return None
