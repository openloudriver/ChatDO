"""
Deterministic fact key/value normalizers.

These are total functions (never throw) that sanitize and canonicalize
fact keys and values. They return sanitized values even for invalid input,
with optional warnings logged.
"""
import re
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# Constants
MAX_FACT_KEY_LENGTH = 200
MAX_FACT_VALUE_LENGTH = 256  # For ranked list values
MAX_GENERIC_VALUE_LENGTH = 1000  # For other facts


def normalize_fact_key(key: str) -> Tuple[str, Optional[str]]:
    """
    Normalize a fact key to canonical form.
    
    This is a total function - it never throws, always returns a sanitized key.
    
    Rules:
    - Trim whitespace
    - Collapse multiple spaces to single space
    - Remove control characters
    - Clamp length to MAX_FACT_KEY_LENGTH
    - Ensure it starts with a valid prefix (user., system., etc.)
    
    Args:
        key: Raw fact key
        
    Returns:
        Tuple of (normalized_key, warning_message)
        warning_message is None if no issues, otherwise contains a warning
    """
    if not key:
        return "user.unknown", "Empty fact key provided"
    
    # Trim and collapse whitespace
    normalized = " ".join(key.split())
    
    # Remove control characters (keep printable ASCII + Unicode)
    normalized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', normalized)
    
    # Ensure it starts with a valid prefix
    if not normalized.startswith(("user.", "system.")):
        # Auto-prefix with user. if missing
        if not normalized.startswith("user."):
            normalized = f"user.{normalized}"
            logger.debug(f"[FACTS-NORM] Auto-prefixed fact key with 'user.': {normalized}")
    
    # Clamp length
    original_length = len(normalized)
    if len(normalized) > MAX_FACT_KEY_LENGTH:
        normalized = normalized[:MAX_FACT_KEY_LENGTH]
        warning = f"Fact key truncated from {original_length} to {MAX_FACT_KEY_LENGTH} chars"
        logger.warning(f"[FACTS-NORM] {warning}: {normalized}")
        return normalized, warning
    
    # Validate format (basic check)
    if not re.match(r'^[a-z][a-z0-9_.]*$', normalized, re.IGNORECASE):
        warning = f"Fact key contains unusual characters: {normalized}"
        logger.warning(f"[FACTS-NORM] {warning}")
        return normalized, warning
    
    return normalized, None


def normalize_fact_value(value: str, is_ranked_list: bool = False) -> Tuple[str, Optional[str]]:
    """
    Normalize a fact value.
    
    This is a total function - it never throws, always returns a sanitized value.
    
    Rules:
    - Trim whitespace
    - Collapse multiple spaces to single space
    - Remove control characters (except newlines for multi-line values)
    - Clamp length (shorter for ranked lists)
    
    Args:
        value: Raw fact value
        is_ranked_list: Whether this is a ranked list value (stricter length limit)
        
    Returns:
        Tuple of (normalized_value, warning_message)
    """
    if not value:
        return "", "Empty fact value provided"
    
    # Trim and normalize whitespace (preserve single newlines)
    normalized = value.strip()
    # Collapse multiple spaces to single space
    normalized = re.sub(r' +', ' ', normalized)
    # Collapse multiple newlines to double newline max
    normalized = re.sub(r'\n{3,}', '\n\n', normalized)
    
    # Remove control characters (keep newlines and tabs)
    normalized = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', normalized)
    
    # Clamp length
    max_length = MAX_FACT_VALUE_LENGTH if is_ranked_list else MAX_GENERIC_VALUE_LENGTH
    original_length = len(normalized)
    if len(normalized) > max_length:
        normalized = normalized[:max_length]
        warning = f"Fact value truncated from {original_length} to {max_length} chars"
        logger.warning(f"[FACTS-NORM] {warning}")
        return normalized, warning
    
    return normalized, None


def canonical_list_key(topic: str) -> str:
    """
    Generate canonical list key from topic.
    
    Schema: user.favorites.<topic>
    
    Uses canonicalize_topic() to ensure consistent topic normalization.
    
    Args:
        topic: Topic name (e.g., "crypto", "colors", "candies")
        
    Returns:
        Canonical list key (e.g., "user.favorites.crypto")
    """
    from server.services.facts_topic import canonicalize_topic
    
    # Use canonical topic normalization (single source of truth)
    canonical_topic = canonicalize_topic(topic)
    
    return f"user.favorites.{canonical_topic}"


def canonical_rank_key(topic: str, rank: int) -> str:
    """
    Generate canonical rank key from topic and rank.
    
    Schema: user.favorites.<topic>.<rank>
    
    Args:
        topic: Topic name (e.g., "crypto")
        rank: Rank number (1-based)
        
    Returns:
        Canonical rank key (e.g., "user.favorites.crypto.1")
    """
    list_key = canonical_list_key(topic)
    return f"{list_key}.{rank}"


def extract_topic_from_list_key(list_key: str) -> Optional[str]:
    """
    Extract topic from a canonical list key.
    
    Example: "user.favorites.crypto" -> "crypto"
    
    Args:
        list_key: Canonical list key
        
    Returns:
        Topic name or None if format doesn't match
    """
    match = re.match(r'^user\.favorites\.([^.]+)$', list_key)
    if match:
        return match.group(1)
    return None

