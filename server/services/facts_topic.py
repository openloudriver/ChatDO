"""
Canonical topic normalization for Facts system.

This module provides the SINGLE SOURCE OF TRUTH for topic canonicalization
used across Facts-S, Facts-U, and Facts-R. All topics are normalized to
a consistent, singular, token-safe format.
"""
import re
import logging

logger = logging.getLogger(__name__)


def canonicalize_topic(raw: str) -> str:
    """
    Canonicalize a topic name to a consistent, singular, token-safe format.
    
    This is the ONLY topic normalization function used in Facts.
    All Facts-S/U/R operations must use this function to ensure consistency.
    
    Rules:
    1. Lowercase
    2. Trim whitespace
    3. Remove "favorite(s)" prefix if present
    4. Convert spaces/hyphens to underscores
    5. Singularize deterministically:
       - If ends with "ies" → replace with "y" (candies → candy)
       - If ends with "s" and not "ss" → drop trailing "s" (cryptos → crypto, colors → color)
    6. Remove any non-alphanumeric characters except underscores
    7. Collapse multiple underscores to single underscore
    
    Args:
        raw: Raw topic string (e.g., "My Favorite Candies", "cryptos", "colors")
        
    Returns:
        Canonical topic string (e.g., "candy", "crypto", "color")
        
    Examples:
        "My Favorite Candies" → "candy"
        "candies" → "candy"
        "cryptos" → "crypto"
        "colors" → "color"
        "favorite-crypto" → "crypto"
        "favorites crypto" → "crypto"
    """
    if not raw:
        return ""
    
    # Step 1: Lowercase
    normalized = raw.lower().strip()
    
    # Step 2: Remove "favorite(s)" prefix if present (anywhere in the string)
    # Match "favorite" or "favorites" optionally followed by spaces/hyphens/underscores
    normalized = re.sub(r'\bfavorites?\s*[-_\s]*', '', normalized, flags=re.IGNORECASE)
    normalized = normalized.strip()
    
    # Also remove "my" prefix if present
    normalized = re.sub(r'^my\s*[-_\s]*', '', normalized, flags=re.IGNORECASE)
    normalized = normalized.strip()
    
    # Step 3: Convert spaces and hyphens to underscores
    normalized = re.sub(r'[\s-]+', '_', normalized)
    
    # Step 4: Remove non-alphanumeric characters except underscores
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    
    # Step 5: Collapse multiple underscores to single underscore
    normalized = re.sub(r'_+', '_', normalized)
    
    # Step 6: Remove leading/trailing underscores
    normalized = normalized.strip('_')
    
    # Step 7: Singularize deterministically
    if normalized.endswith('ies'):
        # candies → candy, cities → city
        normalized = normalized[:-3] + 'y'
    elif normalized.endswith('s') and not normalized.endswith('ss'):
        # cryptos → crypto, colors → color (but keep "class", "pass", etc.)
        # Only drop 's' if it's a plural marker (word is longer than 2 chars)
        if len(normalized) > 2:
            normalized = normalized[:-1]
    
    # Step 8: Final cleanup - ensure it's not empty
    if not normalized:
        logger.warning(f"[FACTS-TOPIC] Empty topic after canonicalization of '{raw}'")
        return "unknown"
    
    return normalized

