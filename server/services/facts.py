"""
Deterministic topic extraction and facts management for ChatDO.

This module provides:
1. Deterministic topic key normalization (STRICT, canonical keys only)
2. Clean ranked facts extraction (no junk tokens)
3. Facts storage and retrieval
"""
import re
import logging
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


# STRICT canonical topic keys - only these are allowed
CANONICAL_TOPIC_KEYS = {
    'favorite_colors',
    'favorite_cryptos',
    'favorite_tv',
    'favorite_candies'
}

# Topic noun patterns - must match explicit nouns in user message
TOPIC_NOUN_PATTERNS = {
    'favorite_colors': [r'\bcolor(s)?\b'],
    'favorite_cryptos': [r'\bcrypto(s)?\b', r'\bcryptocurrenc(y|ies)\b'],
    'favorite_tv': [r'\btv\s+show(s)?\b', r'\btelevision\s+show(s)?\b', r'\bshow(s)?\b'],
    'favorite_candies': [r'\bcand(y|ies)\b', r'\bchocolate(s)?\b'],
}


def normalize_topic_key(text: str) -> Optional[str]:
    """
    STRICT topic key normalization - only returns canonical keys.
    
    Determines topic strictly from explicit nouns in the user message.
    Never maps an ordinal query that mentions "tv/show" to colors or cryptos.
    
    Args:
        text: Natural language text
        
    Returns:
        Canonical topic key or None if no confident match
    """
    text_lower = text.lower().strip()
    
    # Check each canonical topic key's noun patterns
    for topic_key, patterns in TOPIC_NOUN_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                logger.debug(f"[FACTS] Normalized '{text}' -> '{topic_key}' (matched pattern: {pattern})")
                return topic_key
    
    # If no match found, return None (do NOT guess)
    logger.debug(f"[FACTS] No topic key match for '{text}' - returning None")
    return None


def extract_ranked_facts(text: str) -> List[Tuple[int, str]]:
    """
    Deterministic ranked-facts extractor that cannot store junk.
    
    Pre-cleans text to remove citations, markdown, etc.
    Then parses ranks using strict patterns only.
    
    Args:
        text: User message text
        
    Returns:
        List of (rank, value) tuples, sorted by rank ASC
    """
    # Pre-clean: Remove memory citations + tokens
    cleaned = text
    cleaned = re.sub(r'\[M\d+(?:,\s*M\d+)*\]', '', cleaned)  # [M1], [M1, M2]
    cleaned = re.sub(r'\bM\d+\b', '', cleaned)  # M1, M2
    cleaned = re.sub(r'\[\d+\]', '', cleaned)  # [1], [2]
    
    # Remove markdown headings (entire lines starting with #)
    lines = cleaned.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('#'):
            continue  # Skip markdown heading lines
        if stripped.startswith('Model:'):
            continue  # Skip "Model:" lines
        if re.match(r'^\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}', stripped):
            continue  # Skip timestamp-like footer lines
        cleaned_lines.append(line)
    cleaned = '\n'.join(cleaned_lines)
    
    # Parse ranks using ONLY these patterns
    ranked_facts = []
    
    # Pattern 1: (\d+)\s*[\)\.\:]\s*([^,\n]+)  (supports 1) Blue / 2. Green / 3: Black)
    pattern1 = re.compile(r'(\d+)\s*[\)\.\:]\s*([^,\n]+)', re.IGNORECASE)
    for match in pattern1.finditer(cleaned):
        rank_str, value = match.groups()
        rank = int(rank_str)
        value = value.strip().rstrip(',').strip()
        
        # Validate rank and value
        if rank >= 1 and value:
            # Clean value: remove trailing junk tokens
            value = re.sub(r'\s*\[M\d+(?:,\s*M\d+)*\]\s*$', '', value)  # Remove trailing [M1]
            value = re.sub(r'\s*##+\s*$', '', value)  # Remove trailing ##
            value = re.sub(r'\s*M\d+\s*$', '', value)  # Remove trailing M1
            value = value.strip()
            
            # Reject values that are just labels/tokens or empty after cleaning
            if value and not re.match(r'^(M\d+|##+|Model:.*)$', value, re.IGNORECASE):
                ranked_facts.append((rank, value))
    
    # Pattern 2: #(\d+)\s+([^,\n]+)  (supports #1 XMR)
    pattern2 = re.compile(r'#(\d+)\s+([^,\n]+)', re.IGNORECASE)
    for match in pattern2.finditer(cleaned):
        rank_str, value = match.groups()
        rank = int(rank_str)
        value = value.strip().rstrip(',').strip()
        
        # Validate rank and value
        if rank >= 1 and value:
            # Reject values that are just labels/tokens
            if not re.match(r'^(M\d+|##+|Model:.*)$', value, re.IGNORECASE):
                # Avoid duplicates (if already found by pattern1)
                if not any(r == rank for r, _ in ranked_facts):
                    ranked_facts.append((rank, value))
    
    # Pattern 3: Ordinal words (first|second|third|fourth|fifth mapped to 1..5)
    ordinal_map = {
        'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5
    }
    pattern3 = re.compile(r'\b(first|second|third|fourth|fifth)\s*[:]\s*([^,\n]+)', re.IGNORECASE)
    for match in pattern3.finditer(cleaned):
        ordinal_str, value = match.groups()
        rank = ordinal_map.get(ordinal_str.lower())
        if rank:
            value = value.strip().rstrip(',').strip()
            
            # Validate rank and value
            if rank >= 1 and value:
                # Reject values that are just labels/tokens
                if not re.match(r'^(M\d+|##+|Model:.*)$', value, re.IGNORECASE):
                    # Avoid duplicates
                    if not any(r == rank for r, _ in ranked_facts):
                        ranked_facts.append((rank, value))
    
    # Sort by rank ASC and return
    ranked_facts.sort(key=lambda x: x[0])
    return ranked_facts


def extract_topic_from_query(query: str) -> Optional[str]:
    """
    Extract topic from a user query for facts retrieval.
    
    Uses STRICT normalization - only returns canonical keys.
    
    Args:
        query: User query text
        
    Returns:
        Canonical topic key or None if no confident match
    """
    return normalize_topic_key(query)
