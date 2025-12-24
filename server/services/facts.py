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
    
    Extracts the topic noun from queries like:
    - "What are my favorite cryptos?" -> "cryptos"
    - "Please list my favorite colors" -> "colors"
    - "My favorite candies are..." -> "candies"
    
    Args:
        query: User query text
        
    Returns:
        Canonical topic key (e.g., "favorite_crypto", "favorite_color") or None if no match
    """
    try:
        import re
        query_lower = query.lower()
        
        # Pattern 1: "favorite X" or "favorite X are" (most common)
        # Matches: "my favorite cryptos", "favorite colors", "favorite candies are"
        pattern1 = re.search(r'favorite\s+(\w+(?:\s+\w+)?)', query_lower)
        if pattern1:
            topic_noun = pattern1.group(1).strip()
            # Remove trailing "are", "is", etc.
            topic_noun = re.sub(r'\s+(are|is|was|were)$', '', topic_noun)
            
            # Normalize using fact_extractor's normalization
            from memory_service.fact_extractor import get_fact_extractor
            extractor = get_fact_extractor()
            normalized = extractor._normalize_topic(topic_noun)
            return normalized
        
        # Pattern 2: "list my X" or "show my X"
        pattern2 = re.search(r'(?:list|show)\s+(?:my|all|your)?\s*(?:favorite\s+)?(\w+(?:\s+\w+)?)', query_lower)
        if pattern2:
            topic_noun = pattern2.group(1).strip()
            from memory_service.fact_extractor import get_fact_extractor
            extractor = get_fact_extractor()
            normalized = extractor._normalize_topic(topic_noun)
            return normalized
        
        return None
    except Exception as e:
        logger.warning(f"Failed to extract topic from query '{query}': {e}")
        return None
