"""
Shared ordinal detection for router and query planner.

This module provides a single source of truth for detecting ordinal ranks
in user queries (second, third, #2, 2nd, etc.).
"""
import re
from typing import Optional


def detect_ordinal_rank(text: str) -> Optional[int]:
    """
    Detect if a query contains an ordinal rank request.
    
    Supports:
    - Ordinal words: first, second, third, fourth, fifth, etc. (up to tenth)
    - Numeric ordinals: 1st, 2nd, 3rd, 4th, etc.
    - Hash notation: #1, #2, #3, etc.
    - Number notation: number 1, number 2, etc.
    - "favorite #N" patterns
    
    Args:
        text: The user's query text
        
    Returns:
        Integer rank (1-based) if detected, None otherwise
        Examples:
        - "second favorite" -> 2
        - "3rd favorite" -> 3
        - "#2 favorite" -> 2
        - "favorite #1" -> 1
    """
    text_lower = text.lower()
    
    # Pattern 1: Ordinal words (second, third, fourth, etc.)
    ordinal_map = {
        'first': 1, '1st': 1,
        'second': 2, '2nd': 2,
        'third': 3, '3rd': 3,
        'fourth': 4, '4th': 4,
        'fifth': 5, '5th': 5,
        'sixth': 6, '6th': 6,
        'seventh': 7, '7th': 7,
        'eighth': 8, '8th': 8,
        'ninth': 9, '9th': 9,
        'tenth': 10, '10th': 10
    }
    
    for ordinal, rank in ordinal_map.items():
        # Match ordinal word as a whole word (not substring)
        pattern = r'\b' + re.escape(ordinal) + r'\b'
        if re.search(pattern, text_lower):
            return rank
    
    # Pattern 2: Hash notation (#1, #2, #3, etc.)
    hash_match = re.search(r'#(\d+)', text)
    if hash_match:
        rank = int(hash_match.group(1))
        if 1 <= rank <= 10:  # Reasonable bounds
            return rank
    
    # Pattern 3: "number N" or "Nth" (already handled above, but check standalone numbers)
    # Match patterns like "number 2" or "2nd" (already handled) or just "2" in context
    # But be careful - "2" alone could be ambiguous, so require context
    num_with_context = re.search(r'(?:number\s+|#|rank\s+)(\d+)', text_lower)
    if num_with_context:
        rank = int(num_with_context.group(1))
        if 1 <= rank <= 10:
            return rank
    
    return None

