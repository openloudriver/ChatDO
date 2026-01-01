"""
Shared ordinal detection for router and query planner.

This module provides a single source of truth for detecting ordinal ranks
in user queries (second, third, #2, 2nd, etc.) and "top N" slice requests.
"""
import re
from typing import Optional, Tuple


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
    # CRITICAL: Match "#N favorite" pattern specifically to avoid false positives
    # But also allow standalone #N if it's clearly a rank directive
    hash_match = re.search(r'#(\d+)', text)
    if hash_match:
        rank = int(hash_match.group(1))
        # Remove the 10 limit - allow any rank (e.g., #99 for out-of-range queries)
        # But still require reasonable bounds for writes (1-1000 should be enough)
        if 1 <= rank <= 1000:  # Expanded bounds for ranked list mutations
            # Verify this is in a "favorite" context to avoid false positives
            # Look for "favorite" or "rank" nearby (within 20 chars before or after)
            hash_pos = hash_match.start()
            context_start = max(0, hash_pos - 20)
            context_end = min(len(text), hash_pos + 20)
            context = text[context_start:context_end].lower()
            if 'favorite' in context or 'rank' in context or 'number' in context:
                return rank
            # Also allow if it's clearly a rank directive pattern: "my #N favorite" or "#N is"
            if re.search(r'(?:my\s+)?#\d+\s+(?:favorite|is)', context, re.IGNORECASE):
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


def detect_top_n_slice(text: str) -> Optional[int]:
    """
    Detect if a query contains a "top N" slice request.
    
    "Top N" patterns should be interpreted as a SLICE (ranks 1..N), not a singleton rank.
    Examples:
    - "top 3" -> returns 3 (slice of first 3 items)
    - "top three" -> returns 3 (slice of first 3 items)
    - "top 5 favorite activities" -> returns 5 (slice of first 5 items)
    
    This is distinct from singleton rank queries:
    - "#3 favorite" -> should use detect_ordinal_rank (returns 3 for singleton)
    - "third favorite" -> should use detect_ordinal_rank (returns 3 for singleton)
    - "number 3 favorite" -> should use detect_ordinal_rank (returns 3 for singleton)
    
    Args:
        text: The user's query text
        
    Returns:
        Integer N if "top N" pattern detected, None otherwise
        Examples:
        - "top 3 favorite activities" -> 3
        - "top three favorite activities" -> 3
        - "my top 5 favorites" -> 5
    """
    text_lower = text.lower()
    
    # Word-to-number mapping for "top three", "top five", etc.
    word_to_number = {
        'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
        'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
        'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
        'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20
    }
    
    # Pattern 1: "top N" (numeric)
    # Match "top" followed by a number, with optional "favorite" or topic word in between
    top_numeric_pattern = re.compile(r'\btop\s+(\d+)(?:\s+(?:favorite|favorites|my))?', re.IGNORECASE)
    match = top_numeric_pattern.search(text_lower)
    if match:
        n = int(match.group(1))
        if 1 <= n <= 100:  # Reasonable bounds for slice
            return n
    
    # Pattern 2: "top <word-number>" (e.g., "top three", "top five")
    # Match "top" followed by a word number, with optional "favorite" or topic word in between
    top_word_pattern = re.compile(r'\btop\s+(' + '|'.join(word_to_number.keys()) + r')(?:\s+(?:favorite|favorites|my))?', re.IGNORECASE)
    match = top_word_pattern.search(text_lower)
    if match:
        word = match.group(1).lower()
        if word in word_to_number:
            n = word_to_number[word]
            if 1 <= n <= 100:  # Reasonable bounds for slice
                return n
    
    return None


def detect_ordinal_or_slice(text: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Detect both ordinal rank (singleton) and "top N" slice requests.
    
    Returns:
        Tuple of (ordinal_rank, top_n_slice):
        - ordinal_rank: Integer if singleton rank detected (e.g., "#3", "third"), None otherwise
        - top_n_slice: Integer if "top N" slice detected (e.g., "top 3", "top three"), None otherwise
        
    Priority: "top N" takes precedence over ordinal detection to avoid misinterpreting
    "top three" as rank 3 singleton.
    
    Examples:
        - "top 3 favorite activities" -> (None, 3)
        - "top three favorite activities" -> (None, 3)
        - "What is my #3 favorite activity?" -> (3, None)
        - "What is my third favorite activity?" -> (3, None)
        - "What are my top 3 favorite activities?" -> (None, 3)
    """
    # Check for "top N" first (takes precedence)
    top_n = detect_top_n_slice(text)
    if top_n is not None:
        return (None, top_n)
    
    # If no "top N" pattern, check for ordinal rank
    ordinal_rank = detect_ordinal_rank(text)
    return (ordinal_rank, None)

