"""
Centralized Facts parsing utilities.

This module provides a single source of truth for parsing bulk preference values,
ensuring consistent behavior across all Facts write paths.
"""
import re
import logging
from typing import List

logger = logging.getLogger(__name__)


def parse_bulk_preference_values(values_str: str) -> List[str]:
    """
    Parse comma-separated preference lists that may include an Oxford-comma 'and'.

    This is the SINGLE SOURCE OF TRUTH for bulk preference value parsing.
    All Facts write paths must use this function to ensure consistent behavior.

    Examples:
      "Spain, Greece, and Thailand." -> ["Spain", "Greece", "Thailand"]
      "Spain and Greece" -> ["Spain", "Greece"]
      "Spain, Greece and Thailand" -> ["Spain", "Greece", "Thailand"]
      "Mystery, Biography, and Fantasy." -> ["Mystery", "Biography", "Fantasy"]
    
    Args:
        values_str: Raw string containing comma-separated values, possibly with "and"
        
    Returns:
        List of parsed, deduplicated values (preserving order, case-insensitive dedupe)
        Never returns ["and X"] as a value - handles Oxford comma correctly.
    """
    if not values_str:
        return []

    s = values_str.strip()
    # Drop common end-of-sentence punctuation
    s = s.rstrip(".?!")
    
    # Normalize conjunction into comma semantics so split(',') works.
    # Handle Oxford comma and non-Oxford forms.
    # Replace ", and " first (Oxford comma), then " and " (non-Oxford)
    s = s.replace(", and ", ", ")
    s = s.replace(" and ", ", ")

    raw_parts = [p.strip() for p in s.split(",")]
    values: List[str] = []

    for part in raw_parts:
        if not part:
            continue
        # Handle "and X" after stripping removed leading whitespace.
        # This catches cases where the replacement didn't work (edge cases)
        if part.lower().startswith("and "):
            part = part[4:].strip()
        if not part:
            continue
        # Remove surrounding quotes from each part (handles quoted individual items)
        part = part.strip('"').strip("'").strip()
        if not part:
            continue
        values.append(part)

    # De-dupe while preserving order (case-insensitive)
    seen: set[str] = set()
    deduped: List[str] = []
    for v in values:
        key = v.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(v)

    return deduped


def is_bulk_preference_without_rank(text: str) -> bool:
    """
    Detect if a message is a bulk preference statement without explicit ranks.
    
    Matches patterns like:
    - "my favorite X are ..."
    - "my favorites are ..."
    - "my favorite X is A, B, C"
    
    Explicit rank language (e.g., "#4", "fourth", "4th") must bypass this check.
    
    Args:
        text: User message text
        
    Returns:
        True if this is a bulk preference statement without explicit ranks, False otherwise
    """
    import re
    
    text_lower = text.lower().strip()
    
    # Check for explicit rank indicators - if present, this is NOT a bulk preference
    # Pattern: #N favorite OR ordinal word/number favorite (e.g., "#2 favorite", "second favorite", "2nd favorite")
    # Note: \b doesn't work with "#", so we use a more flexible pattern
    explicit_rank_pattern = re.compile(
        r'(?:#\d+\s+|(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th))\s+)favorite',
        re.IGNORECASE
    )
    if explicit_rank_pattern.search(text):
        return False  # Has explicit rank, not a bulk preference
    
    # Check for bulk preference patterns
    # Updated to handle multi-word topics: "vacation destinations", "book genres", etc.
    bulk_patterns = [
        r'my\s+favorite\s+\w+(?:\s+\w+)*\s+are\s+',  # "my favorite X are ..." (supports multi-word topics)
        r'my\s+favorites\s+are\s+',  # "my favorites are ..."
        r'my\s+favorite\s+\w+(?:\s+\w+)*\s+is\s+[^,]+,\s+',  # "my favorite X is A, B, C" (supports multi-word topics)
    ]
    
    for pattern in bulk_patterns:
        if re.search(pattern, text_lower):
            return True
    
    return False

