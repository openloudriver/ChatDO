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
    5. Apply synonym normalization (e.g., "cryptocurrency" → "crypto")
    6. Singularize deterministically:
       - If ends with "ies" → replace with "y" (candies → candy)
       - If ends with "s" and not "ss" → drop trailing "s" (cryptos → crypto, colors → color)
    7. Remove any non-alphanumeric characters except underscores
    8. Collapse multiple underscores to single underscore
    
    Args:
        raw: Raw topic string (e.g., "My Favorite Candies", "cryptos", "cryptocurrencies")
        
    Returns:
        Canonical topic string (e.g., "candy", "crypto", "color")
        
    Examples:
        "My Favorite Candies" → "candy"
        "candies" → "candy"
        "cryptos" → "crypto"
        "cryptocurrency" → "crypto"
        "cryptocurrencies" → "crypto"
        "crypto currency" → "crypto"
        "digital currency" → "crypto"
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
    
    # Step 4: Apply synonym normalization BEFORE singularization
    # This ensures synonyms map to the same canonical topic
    synonym_map = {
        # Cryptocurrency synonyms → "crypto"
        r'\bcryptocurrenc(?:y|ies)\b': 'crypto',
        r'\bcrypto_currenc(?:y|ies)\b': 'crypto',
        r'\bdigital_currenc(?:y|ies)\b': 'crypto',
        r'\bvirtual_currenc(?:y|ies)\b': 'crypto',
        # Add more synonym mappings as needed
        # Example: r'\bautomobile(?:s)?\b': 'car',
        # Example: r'\bvehicle(?:s)?\b': 'car',
    }
    
    for pattern, replacement in synonym_map.items():
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    
    # Step 5: Remove non-alphanumeric characters except underscores
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    
    # Step 6: Collapse multiple underscores to single underscore
    normalized = re.sub(r'_+', '_', normalized)
    
    # Step 7: Remove leading/trailing underscores
    normalized = normalized.strip('_')
    
    # Step 8: Singularize deterministically
    # CRITICAL: Only apply singularization to the last word (after last underscore)
    # This prevents "sci_fi_movies" from being incorrectly converted to "sci_fi_movy"
    # Split by underscore to get words
    words = normalized.split('_')
    if words:
        last_word = words[-1]
        # Apply singularization to last word only
        # Handle plurals: "movies" → "movie", "candies" → "candy", "cities" → "city"
        # Strategy: For words ending in "ies", use a heuristic:
        # - If stem (without "ies") is 4+ chars: apply "ies" → "y" (candies → candy, activities → activity)
        # - If stem is 3 chars: apply "ies" → "y" UNLESS stem ends with "v" (movies → movie)
        #   This handles "cities" → "city" (cit + y) vs "movies" → "movie" (mov + e)
        if last_word.endswith('ies') and len(last_word) > 4:
            stem = last_word[:-3]
            if len(stem) >= 4:
                # Long stem: apply "ies" → "y" (candies → candy, activities → activity)
                words[-1] = stem + 'y'
            elif len(stem) == 3:
                # 3-char stem: check if it ends with "v" (movies → movie) or not (cities → city)
                if stem[-1] == 'v':
                    # "movies" → "movie" (es → e)
                    words[-1] = last_word[:-2] + 'e'
                else:
                    # "cities" → "city" (ies → y)
                    words[-1] = stem + 'y'
            elif len(stem) >= 2:
                # Very short stem: apply "es" → "e"
                words[-1] = last_word[:-2] + 'e'
        elif last_word.endswith('es') and len(last_word) > 3 and not last_word.endswith('ss'):
            # Handle "es" → "e" for words like "houses" → "house"
            # But NOT "candies" or "movies" (already handled above) or "classes" (keep as "class")
            stem = last_word[:-2]
            if len(stem) >= 2:
                words[-1] = stem + 'e'
        elif last_word.endswith('s') and not last_word.endswith('ss') and len(last_word) > 2:
            # Regular plurals: cryptos → crypto, colors → color
            # Only drop 's' if it's a plural marker
            words[-1] = last_word[:-1]
        # Rejoin words
        normalized = '_'.join(words)
    
    # Step 9: Final cleanup - ensure it's not empty
    if not normalized:
        logger.warning(f"[FACTS-TOPIC] Empty topic after canonicalization of '{raw}'")
        return "unknown"
    
    return normalized

