"""
Deterministic Facts Operations Applier.

This is the SINGLE SOURCE OF TRUTH for all fact writes.
No other code path should write facts to the database.
"""
import logging
import uuid
import unicodedata
import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

from server.contracts.facts_ops import FactsOp, FactsOpsResponse
from server.services.facts_normalize import (
    normalize_fact_key,
    normalize_fact_value,
    canonical_rank_key,
    canonical_list_key,
    extract_topic_from_list_key
)
from server.services.projects.project_resolver import validate_project_uuid
from memory_service.memory_dashboard import db

logger = logging.getLogger(__name__)


def _get_max_rank_atomic(
    conn,
    project_uuid: str,
    topic: str,
    list_key: str
) -> int:
    """
    Atomically get the maximum rank for a topic within a transaction.
    
    This function must be called within an active transaction to ensure
    atomicity and prevent race conditions.
    
    Args:
        conn: Active database connection (must be in a transaction)
        project_uuid: Project UUID
        topic: Canonical topic
        list_key: List key (e.g., "user.favorites.crypto")
        
    Returns:
        Maximum rank found (0 if no facts exist)
    """
    cursor = conn.cursor()
    
    # Query all ranked facts for this topic (using list_key prefix)
    # Pattern: user.favorites.<topic>.<rank>
    cursor.execute("""
        SELECT fact_key, value_text
        FROM project_facts
        WHERE project_id = ? AND fact_key LIKE ? AND is_current = 1
        ORDER BY fact_key
    """, (project_uuid, f"{list_key}.%"))
    
    rows = cursor.fetchall()
    max_rank = 0
    
    for row in rows:
        fact_key = row[0]
        # Extract rank from fact_key (e.g., "user.favorites.crypto.5" -> 5)
        if "." in fact_key:
            try:
                rank_str = fact_key.rsplit(".", 1)[1]
                rank = int(rank_str)
                if rank > max_rank:
                    max_rank = rank
            except (ValueError, IndexError):
                # Skip invalid rank format
                continue
    
    return max_rank


def normalize_rank_item(s: str) -> str:
    """
    Canonical normalizer for ranked-list items (shared by write + apply).
    
    This is the SINGLE SOURCE OF TRUTH for ranked item normalization.
    Used for duplicate detection and matching across all ranked list operations.
    
    Normalization steps:
    1. Unicode normalization (NFKC) - handles composed/decomposed characters
    2. Map smart quotes to ASCII equivalents (' → ', " → ")
    3. Strip leading/trailing whitespace
    4. Collapse internal whitespace to single spaces
    5. Strip trailing punctuation: .,!?;:
    6. Lowercase (for comparison only - original value is preserved)
    
    Args:
        s: Raw value string
        
    Returns:
        Normalized string for comparison (lowercased)
        
    Examples:
        "Breakfast Burritos" → "breakfast burritos"
        "breakfast burritos." → "breakfast burritos"
        "  Breakfast  Burritos  " → "breakfast burritos"
        "Breakfast's Burritos" (smart quote) → "breakfast's burritos"
    """
    return normalize_favorite_value(s)


def _tokenize_normalized(s: str) -> set:
    """
    Tokenize a normalized string into a set of words.
    
    Args:
        s: Normalized string (already lowercased, whitespace collapsed)
        
    Returns:
        Set of tokens (words), excluding very short words
    """
    # Split on whitespace and filter out very short words (1-2 chars) and common stop words
    tokens = [t for t in s.split() if len(t) > 2]
    return set(tokens)


def resolve_ranked_item_target(
    new_value: str,
    existing_items: List[Dict[str, Any]],
    threshold: float = 0.85
) -> Optional[Dict[str, Any]]:
    """
    Resolve a new value to an existing ranked item using exact or fuzzy/alias matching.
    
    This enables partial/alias values (e.g., "rogue one") to match full canonical items
    (e.g., "Star Wars: Rogue One").
    
    Matching strategy:
    1. Exact normalized match (highest priority)
    2. Fuzzy/alias match using token subset score and Jaccard similarity
    
    Args:
        new_value: New value string (user-provided, may be partial/alias)
        existing_items: List of existing ranked items with keys: value_text, rank, fact_key
        threshold: Minimum fuzzy match score (0.0-1.0) to consider a match
        
    Returns:
        Matched existing item dict if found, None otherwise
        
    Examples:
        new_value="rogue one", existing="Star Wars: Rogue One" → match (all tokens found)
        new_value="breath of the wild", existing="The Legend of Zelda: Breath of the Wild" → match
        new_value="matrix", existing="The Matrix" → match (subset score = 1.0)
    """
    if not existing_items:
        return None
    
    # Normalize new value
    normalized_new = normalize_rank_item(new_value)
    tokens_new = _tokenize_normalized(normalized_new)
    
    if not tokens_new:
        # Empty or only stop words - can't match
        return None
    
    # First, try exact normalized match (highest priority)
    for item in existing_items:
        normalized_existing = normalize_rank_item(item["value_text"])
        if normalized_existing == normalized_new:
            logger.debug(
                f"[FACTS-APPLY] Exact match: '{new_value}' → '{item['value_text']}' "
                f"(rank {item['rank']})"
            )
            return item
    
    # If no exact match, try fuzzy/alias matching
    best_match = None
    best_score = 0.0
    
    for item in existing_items:
        normalized_existing = normalize_rank_item(item["value_text"])
        tokens_existing = _tokenize_normalized(normalized_existing)
        
        if not tokens_existing:
            continue
        
        # Compute subset score: how many of new_value's tokens are in existing?
        # This handles cases like "rogue one" matching "Star Wars: Rogue One"
        intersection = tokens_new.intersection(tokens_existing)
        subset_score = len(intersection) / len(tokens_new) if tokens_new else 0.0
        
        # Compute Jaccard similarity as tie-breaker
        union = tokens_new.union(tokens_existing)
        jaccard = len(intersection) / len(union) if union else 0.0
        
        # Combined score: prioritize subset score (all tokens found = perfect match)
        # Use Jaccard as tie-breaker when subset scores are equal
        if subset_score == 1.0:
            # Perfect subset match - all tokens from new_value are in existing
            # This is the ideal case (e.g., "rogue one" → "Star Wars: Rogue One")
            score = 1.0 + jaccard  # Boost perfect subset matches
        elif subset_score >= threshold:
            # Good enough match
            score = subset_score + (jaccard * 0.1)  # Jaccard as minor tie-breaker
        else:
            # Below threshold
            continue
        
        if score > best_score:
            best_score = score
            best_match = item
    
    if best_match:
        logger.info(
            f"[FACTS-APPLY] Alias/fuzzy match: '{new_value}' → '{best_match['value_text']}' "
            f"(rank {best_match['rank']}, score={best_score:.3f})"
        )
        return best_match
    
    return None


def normalize_favorite_value(s: str) -> str:
    """
    Normalize a favorite value for duplicate detection.
    
    DEPRECATED: Use normalize_rank_item() instead for consistency.
    This function is kept for backward compatibility.
    
    This is the SINGLE SOURCE OF TRUTH for favorite value normalization.
    All duplicate checks for favorites must use this function to ensure
    consistent comparison across variations like:
    - "Reese's" vs "Reese's." vs "reese's " vs "Reese's"
    
    Normalization steps:
    1. Unicode normalization (NFKC) - handles composed/decomposed characters
    2. Map smart quotes to ASCII equivalents (' → ', " → ")
    3. Strip leading/trailing whitespace
    4. Collapse internal whitespace to single spaces
    5. Strip trailing punctuation: .,!?;:
    6. Lowercase (for comparison only - original value is preserved)
    
    Args:
        s: Raw value string
        
    Returns:
        Normalized string for comparison (lowercased)
        
    Examples:
        "Reese's" → "reese's"
        "Reese's." → "reese's"
        "  reese's  " → "reese's"
        "Reese's" (smart quote) → "reese's"
    """
    if not s:
        return ""
    
    # Step 1: Unicode normalization (NFKC)
    # This handles composed/decomposed characters (e.g., é vs é)
    normalized = unicodedata.normalize("NFKC", s)
    
    # Step 2: Map smart quotes to ASCII equivalents
    # Map various apostrophe/quotation mark characters to standard ASCII
    quote_map = {
        '\u2018': "'",  # Left single quotation mark
        '\u2019': "'",  # Right single quotation mark (most common)
        '\u201A': "'",  # Single low-9 quotation mark
        '\u201B': "'",  # Single high-reversed-9 quotation mark
        '\u2032': "'",  # Prime
        '\u201C': '"',  # Left double quotation mark
        '\u201D': '"',  # Right double quotation mark
        '\u201E': '"',  # Double low-9 quotation mark
        '\u201F': '"',  # Double high-reversed-9 quotation mark
        '\u2033': '"',  # Double prime
    }
    for smart_char, ascii_char in quote_map.items():
        normalized = normalized.replace(smart_char, ascii_char)
    
    # Step 3: Strip leading/trailing whitespace
    normalized = normalized.strip()
    
    # Step 4: Collapse internal whitespace to single spaces
    normalized = re.sub(r'\s+', ' ', normalized)
    
    # Step 5: Strip trailing punctuation: .,!?;:
    normalized = re.sub(r'[.,!?;:]+$', '', normalized)
    
    # Step 6: Lowercase for comparison
    normalized = normalized.lower()
    
    return normalized


def _check_ranked_list_exists(
    conn,
    project_uuid: str,
    list_key: str
) -> bool:
    """
    Check if a ranked list already exists for a topic.
    
    This function must be called within an active transaction to ensure
    atomicity and prevent race conditions.
    
    Args:
        conn: Active database connection (must be in a transaction)
        project_uuid: Project UUID
        list_key: List key (e.g., "user.favorites.crypto")
        
    Returns:
        True if any ranked facts exist for this topic, False otherwise
    """
    cursor = conn.cursor()
    
    # Query for any ranked facts for this topic (using list_key prefix)
    # Pattern: user.favorites.<topic>.<rank>
    cursor.execute("""
        SELECT COUNT(*) 
        FROM project_facts
        WHERE project_id = ? AND fact_key LIKE ? AND is_current = 1
    """, (project_uuid, f"{list_key}.%"))
    
    count = cursor.fetchone()[0]
    return count > 0


def _get_ranked_list_items(
    conn,
    project_uuid: str,
    list_key: str
) -> List[Dict[str, Any]]:
    """
    Get all ranked list items for a topic, sorted by rank.
    
    This function must be called within an active transaction.
    
    Args:
        conn: Active database connection (must be in a transaction)
        project_uuid: Project UUID
        list_key: List key (e.g., "user.favorites.crypto")
        
    Returns:
        List of dicts with keys: fact_key, rank, value_text
    """
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT fact_key, value_text
        FROM project_facts
        WHERE project_id = ? AND fact_key LIKE ? AND is_current = 1
        ORDER BY fact_key
    """, (project_uuid, f"{list_key}.%"))
    
    rows = cursor.fetchall()
    items = []
    
    for row in rows:
        fact_key = row[0]
        value_text = row[1] if len(row) > 1 else ""
        
        # Extract rank from fact_key (e.g., "user.favorites.crypto.2" -> 2)
        if "." in fact_key:
            try:
                rank_str = fact_key.rsplit(".", 1)[1]
                rank = int(rank_str)
                items.append({
                    "fact_key": fact_key,
                    "rank": rank,
                    "value_text": value_text
                })
            except (ValueError, IndexError):
                continue
    
    return items


def _apply_ranked_mutation(
    conn,
    cursor,
    project_uuid: str,
    canonical_topic: str,
    list_key: str,
    desired_rank: int,
    value: str,
    message_uuid: str,
    normalized_value: str
) -> Dict[str, Any]:
    """
    Apply a ranked mutation operation: MOVE, INSERT, or NO-OP.
    
    This is the SINGLE SOURCE OF TRUTH for ranked list mutations.
    
    Behavior:
    1. If value already exists at rank K != desired_rank:
       - MOVE value to desired_rank
       - Shift intervening items accordingly (stable, no duplicates)
    2. If value already exists at desired_rank:
       - NO-OP and return {"action": "noop", "existing_rank": desired_rank}
    3. If value does NOT exist in the list:
       - INSERT value at desired_rank (shift items at desired_rank..end down by 1)
    4. If desired_rank > len(list)+1:
       - Append to end (rank = len(list)+1)
    
    Args:
        conn: Active database connection (must be in a transaction)
        cursor: Database cursor
        project_uuid: Project UUID
        canonical_topic: Canonical topic name
        list_key: List key (e.g., "user.favorites.crypto")
        desired_rank: Desired rank (1-based)
        value: Raw value string (user-provided)
        message_uuid: Message UUID for fact storage
        normalized_value: Normalized value (for storage)
        
    Returns:
        Dict with keys:
        - action: "move" | "insert" | "noop" | "append"
        - old_rank: Previous rank if moved, None otherwise
        - new_rank: Final rank assigned
        - shifted_items: List of (old_rank, new_rank, value) for items that were shifted
    """
    # Get current ranked list
    items = _get_ranked_list_items(conn, project_uuid, list_key)
    current_max_rank = len(items)
    
    # CRITICAL: Resolve new value to existing item using exact or fuzzy/alias matching
    # This enables partial values (e.g., "rogue one") to match full items (e.g., "Star Wars: Rogue One")
    matched_item = resolve_ranked_item_target(value, items)
    
    # Find ALL occurrences of the matched item (if found) or exact normalized matches
    # This prevents duplicates from persisting when moving/inserting items
    normalized_input = normalize_rank_item(value)
    existing_items = []
    
    if matched_item:
        # Use the matched item's normalized form to find all occurrences
        matched_normalized = normalize_rank_item(matched_item["value_text"])
        for item in items:
            if normalize_rank_item(item["value_text"]) == matched_normalized:
                existing_items.append(item)
    else:
        # No fuzzy match found - try exact normalized match
        for item in items:
            if normalize_rank_item(item["value_text"]) == normalized_input:
                existing_items.append(item)
    
    # Get the first existing item for move logic (if any)
    existing_rank = existing_items[0]["rank"] if existing_items else None
    existing_item = existing_items[0] if existing_items else None
    
    # If we found a fuzzy match, use the matched item's canonical value for storage
    if matched_item:
        # Use the canonical value from the matched item (preserves full title like "Star Wars: Rogue One")
        # but keep the user's input for logging/display
        canonical_value = matched_item["value_text"]
        logger.info(
            f"[FACTS-APPLY] Using canonical value from fuzzy match: '{value}' → '{canonical_value}' "
            f"for mutation to rank {desired_rank}"
        )
        # Update normalized_value to use the canonical value
        normalized_value, _ = normalize_fact_value(canonical_value, is_ranked_list=True)
        
        # Ensure we have the existing item for move logic
        if not existing_item:
            existing_item = matched_item
            existing_rank = matched_item["rank"]
            existing_items = [matched_item]
    
    # CRITICAL FIX: Remove ALL duplicates BEFORE inserting/moving
    # This ensures "Breakfast Burritos" doesn't appear at multiple ranks
    if existing_items:
        logger.info(
            f"[FACTS-APPLY] Found {len(existing_items)} duplicate(s) of '{value}' "
            f"(normalized: '{normalized_input}') at ranks: {[item['rank'] for item in existing_items]}. "
            f"Removing all duplicates before mutation."
        )
        for dup_item in existing_items:
            old_fact_key = dup_item["fact_key"]
            cursor.execute("""
                UPDATE project_facts
                SET is_current = 0
                WHERE project_id = ? AND fact_key = ? AND is_current = 1
            """, (project_uuid, old_fact_key))
            logger.debug(
                f"[FACTS-APPLY] Marked duplicate as not current: rank={dup_item['rank']}, "
                f"value='{dup_item['value_text']}', fact_key={old_fact_key}"
            )
    
    # Handle rank beyond length: append to end
    if desired_rank > current_max_rank + 1:
        desired_rank = current_max_rank + 1
        logger.info(
            f"[FACTS-APPLY] Rank {desired_rank} beyond list length ({current_max_rank}), "
            f"appending to end at rank {desired_rank}"
        )
    
    result = {
        "action": None,
        "old_rank": None,
        "new_rank": desired_rank,
        "shifted_items": []
    }
    
    if existing_rank is not None:
        # Value already exists
        if existing_rank == desired_rank:
            # Already at desired rank: NO-OP
            result["action"] = "noop"
            result["old_rank"] = desired_rank
            logger.info(
                f"[FACTS-APPLY] Rank mutation NO-OP: '{value}' already at rank {desired_rank} "
                f"for topic={canonical_topic}"
            )
            return result
        
        # MOVE: Value exists at different rank, move to desired_rank
        # Note: All duplicates have already been removed above
        result["action"] = "move"
        result["old_rank"] = existing_rank
        
        # Old fact has already been marked as not current in the duplicate removal step above
        # No need to mark it again here
        
        # Determine shift direction and range
        # Note: Lower rank number = earlier in list (rank 1 is first)
        if existing_rank > desired_rank:
            # Moving earlier in list (e.g., rank 6 -> rank 2): shift items at desired_rank..(existing_rank-1) down by 1
            # Example: moving from 6 to 2, shift items at ranks 2-5 down to ranks 3-6
            shift_start = desired_rank
            shift_end = existing_rank - 1
            shift_delta = +1
        else:
            # Moving later in list (e.g., rank 2 -> rank 6): shift items at (existing_rank+1)..desired_rank up by 1
            # Example: moving from 2 to 6, shift items at ranks 3-6 up to ranks 2-5
            shift_start = existing_rank + 1
            shift_end = desired_rank
            shift_delta = -1
        
        # Shift intervening items (exclude the item being moved AND any duplicates we just removed)
        # IMPORTANT: Shift in the correct order to avoid overwriting items that haven't been shifted yet
        # When moving down (existing_rank > desired_rank): shift from end backwards (high to low)
        # When moving up (existing_rank < desired_rank): shift from start forwards (low to high)
        existing_ranks = {item["rank"] for item in existing_items}  # All ranks that were duplicates
        items_to_shift = [
            item for item in items
            if item["rank"] not in existing_ranks and shift_start <= item["rank"] <= shift_end
        ]
        
        if existing_rank > desired_rank:
            # Moving down: shift from end backwards (rank 5, 4, 3, 2)
            items_to_shift.sort(key=lambda x: x["rank"], reverse=True)
        else:
            # Moving up: shift from start forwards (rank 3, 4, 5, 6)
            items_to_shift.sort(key=lambda x: x["rank"])
        
        for item in items_to_shift:
            item_rank = item["rank"]
            new_rank = item_rank + shift_delta
            old_fact_key = item["fact_key"]
            new_fact_key = canonical_rank_key(canonical_topic, new_rank)
            
            # Mark old fact as not current
            cursor.execute("""
                UPDATE project_facts
                SET is_current = 0
                WHERE project_id = ? AND fact_key = ? AND is_current = 1
            """, (project_uuid, old_fact_key))
            
            # Insert shifted fact at new rank
            fact_id = str(uuid.uuid4())
            created_at = datetime.now()
            cursor.execute("""
                INSERT INTO project_facts (
                    fact_id, project_id, fact_key, value_text, value_type,
                    confidence, source_message_uuid, created_at, effective_at,
                    supersedes_fact_id, is_current
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                fact_id, project_uuid, new_fact_key, item["value_text"], "string",
                1.0, message_uuid, created_at, created_at, None
            ))
            
            result["shifted_items"].append((item_rank, new_rank, item["value_text"]))
            logger.debug(
                f"[FACTS-APPLY] Shifted item: rank {item_rank} -> {new_rank} "
                f"value='{item['value_text']}'"
            )
        
        # Mark any existing fact at desired_rank as not current (shouldn't happen after shift, but be safe)
        cursor.execute("""
            UPDATE project_facts
            SET is_current = 0
            WHERE project_id = ? AND fact_key = ? AND is_current = 1
        """, (project_uuid, canonical_rank_key(canonical_topic, desired_rank)))
        
        # Insert moved value at desired_rank
        new_fact_key = canonical_rank_key(canonical_topic, desired_rank)
        fact_id = str(uuid.uuid4())
        created_at = datetime.now()
        cursor.execute("""
            INSERT INTO project_facts (
                fact_id, project_id, fact_key, value_text, value_type,
                confidence, source_message_uuid, created_at, effective_at,
                supersedes_fact_id, is_current
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            fact_id, project_uuid, new_fact_key, normalized_value, "string",
            1.0, message_uuid, created_at, created_at, None
        ))
        
        logger.info(
            f"[FACTS-APPLY] Rank mutation MOVE: '{value}' from rank {existing_rank} to {desired_rank} "
            f"for topic={canonical_topic}, removed {len(existing_items)} duplicate(s), "
            f"shifted {len(result['shifted_items'])} items"
        )
        logger.debug(
            f"[FACTS-APPLY] Inserted moved value '{value}' at rank {desired_rank} "
            f"fact_key={new_fact_key}"
        )
        
    else:
        # INSERT: Value doesn't exist, insert at desired_rank
        result["action"] = "insert"
        
        # Shift items at desired_rank..end down by 1
        # IMPORTANT: Exclude any duplicates we just removed (they're already marked as not current)
        # IMPORTANT: Shift from end backwards to avoid overwriting items that haven't been shifted yet
        existing_ranks = {item["rank"] for item in existing_items}  # All ranks that were duplicates
        items_to_shift = [
            item for item in items 
            if item["rank"] >= desired_rank and item["rank"] not in existing_ranks
        ]
        items_to_shift.sort(key=lambda x: x["rank"], reverse=True)  # Shift from end backwards
        
        for item in items_to_shift:
            item_rank = item["rank"]
            new_rank = item_rank + 1
            old_fact_key = item["fact_key"]
            new_fact_key = canonical_rank_key(canonical_topic, new_rank)
            
            # Mark old fact as not current
            cursor.execute("""
                UPDATE project_facts
                SET is_current = 0
                WHERE project_id = ? AND fact_key = ? AND is_current = 1
            """, (project_uuid, old_fact_key))
            
            # Insert shifted fact at new rank
            fact_id = str(uuid.uuid4())
            created_at = datetime.now()
            cursor.execute("""
                INSERT INTO project_facts (
                    fact_id, project_id, fact_key, value_text, value_type,
                    confidence, source_message_uuid, created_at, effective_at,
                    supersedes_fact_id, is_current
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                fact_id, project_uuid, new_fact_key, item["value_text"], "string",
                1.0, message_uuid, created_at, created_at, None
            ))
            
            result["shifted_items"].append((item_rank, new_rank, item["value_text"]))
            logger.debug(
                f"[FACTS-APPLY] Shifted item: rank {item_rank} -> {new_rank} "
                f"value='{item['value_text']}'"
            )
        
        # Insert new value at desired_rank
        new_fact_key = canonical_rank_key(canonical_topic, desired_rank)
        fact_id = str(uuid.uuid4())
        created_at = datetime.now()
        cursor.execute("""
            INSERT INTO project_facts (
                fact_id, project_id, fact_key, value_text, value_type,
                confidence, source_message_uuid, created_at, effective_at,
                supersedes_fact_id, is_current
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            fact_id, project_uuid, new_fact_key, normalized_value, "string",
            1.0, message_uuid, created_at, created_at, None
        ))
        
        logger.info(
            f"[FACTS-APPLY] Rank mutation INSERT: '{value}' at rank {desired_rank} "
            f"for topic={canonical_topic}, removed {len(existing_items)} duplicate(s), "
            f"shifted {len(result['shifted_items'])} items"
        )
    
    # DEBUG LOGGING: Log after state
    final_items = _get_ranked_list_items(conn, project_uuid, list_key)
    logger.info(
        f"[FACTS-APPLY] Ranked mutation END: action={result['action']}, "
        f"final_list_length={len(final_items)}, "
        f"final_items={[(item['rank'], item['value_text']) for item in final_items]}"
    )
    
    return result


def validate_ranked_list_invariants(
    items: List[Dict[str, Any]],
    list_key: str
) -> tuple[bool, Optional[str]]:
    """
    Validate ranked list invariants.
    
    Enforces:
    - Uniqueness: a value may appear only once in the ranked list
    - Contiguous ranks: ranks must be exactly 1..N with no gaps
    - Single rank per value: no duplicates across ranks
    
    Args:
        items: List of ranked items with keys: fact_key, rank, value_text
        list_key: List key for error messages
        
    Returns:
        (is_valid, error_message)
        - is_valid: True if all invariants pass, False otherwise
        - error_message: None if valid, descriptive error if invalid
    """
    if not items:
        return True, None
    
    # Extract ranks and values
    ranks = [item["rank"] for item in items]
    values = [item["value_text"] for item in items]
    
    # Check 1: Contiguous ranks (must be exactly 1..N with no gaps)
    expected_ranks = set(range(1, len(items) + 1))
    actual_ranks = set(ranks)
    
    if expected_ranks != actual_ranks:
        missing = expected_ranks - actual_ranks
        extra = actual_ranks - expected_ranks
        return False, (
            f"Ranked list '{list_key}' has non-contiguous ranks. "
            f"Expected ranks 1..{len(items)}, but found ranks: {sorted(ranks)}. "
            f"Missing: {sorted(missing)}, Extra: {sorted(extra)}"
        )
    
    # Check 2: Uniqueness - no duplicate values (using normalized comparison)
    normalized_values = {}
    for item in items:
        normalized = normalize_favorite_value(item["value_text"])
        if normalized in normalized_values:
            existing_rank = normalized_values[normalized]["rank"]
            existing_value = normalized_values[normalized]["value_text"]
            return False, (
                f"Ranked list '{list_key}' has duplicate values. "
                f"Value '{item['value_text']}' at rank {item['rank']} "
                f"duplicates '{existing_value}' at rank {existing_rank} "
                f"(normalized: '{normalized}')"
            )
        normalized_values[normalized] = item
    
    # Check 3: Single rank per value (implicitly checked by uniqueness above)
    # But also check for duplicate ranks (shouldn't happen if fact_keys are unique)
    rank_counts = {}
    for rank in ranks:
        rank_counts[rank] = rank_counts.get(rank, 0) + 1
        if rank_counts[rank] > 1:
            return False, (
                f"Ranked list '{list_key}' has duplicate rank {rank}. "
                f"Each rank must appear exactly once."
            )
    
    return True, None


def _check_value_exists_in_ranked_list(
    conn,
    project_uuid: str,
    list_key: str,
    value: str
) -> Optional[int]:
    """
    Check if a value already exists in a ranked list and return its rank.
    
    This function must be called within an active transaction to ensure
    atomicity and prevent race conditions.
    
    Args:
        conn: Active database connection (must be in a transaction)
        project_uuid: Project UUID
        list_key: List key (e.g., "user.favorites.crypto")
        value: Value to check for (raw value - will be normalized internally using normalize_favorite_value)
        
    Returns:
        Rank (1-based) if value exists, None otherwise
    """
    cursor = conn.cursor()
    
    # Query all ranked facts for this topic (using list_key prefix)
    # Pattern: user.favorites.<topic>.<rank>
    cursor.execute("""
        SELECT fact_key, value_text
        FROM project_facts
        WHERE project_id = ? AND fact_key LIKE ? AND is_current = 1
        ORDER BY fact_key
    """, (project_uuid, f"{list_key}.%"))
    
    rows = cursor.fetchall()
    
    logger.debug(
        f"[FACTS-APPLY] _check_value_exists_in_ranked_list: "
        f"list_key={list_key}, value='{value}', found {len(rows)} existing facts"
    )
    
    # Normalize the input value once (for comparison)
    normalized_input = normalize_favorite_value(value)
    
    # Optional: Cache normalized existing values to avoid re-normalizing in loop
    # (Lightweight optimization for large lists)
    normalized_cache: Dict[str, str] = {}
    
    for row in rows:
        fact_key = row[0]
        existing_value = row[1] if len(row) > 1 else ""
        
        # Use cached normalized value if available, otherwise normalize and cache
        if existing_value not in normalized_cache:
            normalized_cache[existing_value] = normalize_favorite_value(existing_value)
        normalized_existing = normalized_cache[existing_value]
        
        logger.debug(
            f"[FACTS-APPLY] Comparing: existing='{existing_value}' (norm: '{normalized_existing}') "
            f"vs input='{value}' (norm: '{normalized_input}') -> "
            f"match={normalized_existing == normalized_input}"
        )
        
        # Compare normalized values (both are already lowercased and normalized)
        if normalized_existing and normalized_existing == normalized_input:
            # Extract rank from fact_key (e.g., "user.favorites.crypto.2" -> 2)
            if "." in fact_key:
                try:
                    rank_str = fact_key.rsplit(".", 1)[1]
                    rank = int(rank_str)
                    return rank
                except (ValueError, IndexError):
                    continue
    
    return None


@dataclass
class ApplyResult:
    """Result of applying facts operations."""
    store_count: int = 0
    update_count: int = 0
    stored_fact_keys: List[str] = None
    warnings: List[str] = None
    errors: List[str] = None
    rank_assignment_source: Dict[str, str] = None  # Maps fact_key -> source ("explicit" | "atomic_append")
    duplicate_blocked: Dict[str, Dict[str, Any]] = None  # Maps fact_key -> {"value": str, "existing_rank": int}
    rank_mutations: Dict[str, Dict[str, Any]] = None  # Maps fact_key -> {"action": "move"|"insert"|"noop"|"append", "old_rank": int|None, "new_rank": int, "value": str}
    
    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.stored_fact_keys is None:
            self.stored_fact_keys = []
        if self.warnings is None:
            self.warnings = []
        if self.errors is None:
            self.errors = []
        if self.rank_assignment_source is None:
            self.rank_assignment_source = {}
        if self.duplicate_blocked is None:
            self.duplicate_blocked = {}
        if self.rank_mutations is None:
            self.rank_mutations = {}


def apply_facts_ops(
    project_uuid: str,
    message_uuid: str,
    ops_response: FactsOpsResponse,
    source_id: Optional[str] = None
) -> ApplyResult:
    """
    Apply facts operations deterministically.
    
    This is the ONLY function that writes facts to the database.
    All fact writes must go through this function.
    
    Args:
        project_uuid: Project UUID (must be valid UUID, validated here)
        message_uuid: Message UUID that triggered these operations
        ops_response: FactsOpsResponse containing operations to apply
        source_id: Optional source ID (uses project-based source if not provided)
        
    Returns:
        ApplyResult with counts, keys, warnings, and errors
        
    Raises:
        ValueError: If project_uuid is not a valid UUID
    """
    result = ApplyResult()
    
    # Validate project UUID (hard fail if invalid)
    try:
        validate_project_uuid(project_uuid)
    except ValueError as e:
        result.errors.append(f"Invalid project UUID: {e}")
        logger.error(f"[FACTS-APPLY] {result.errors[-1]}")
        return result
    
    # Check for clarification needed
    if ops_response.needs_clarification:
        result.errors.append(
            f"Clarification needed: {', '.join(ops_response.needs_clarification)}"
        )
        logger.info(f"[FACTS-APPLY] Clarification required, no operations applied")
        return result
    
    if not ops_response.ops:
        logger.debug(f"[FACTS-APPLY] No operations to apply")
        return result
    
    # Use project-based source if not provided
    if source_id is None:
        source_id = f"project-{project_uuid}"
    
    logger.info(
        f"[FACTS-E2E] APPLY: ops_count={len(ops_response.ops)} project_uuid={project_uuid} "
        f"message_uuid={message_uuid}"
    )
    
    # Initialize DB connection for atomic operations
    db.init_db(source_id, project_id=project_uuid)
    conn = db.get_db_connection(source_id, project_id=project_uuid)
    cursor = conn.cursor()
    
    # Start transaction for atomic unranked writes
    # CRITICAL: Use BEGIN IMMEDIATE to acquire reserved lock BEFORE reading max_rank
    # This prevents race conditions where two concurrent transactions both read the same
    # max_rank value before either writes, leading to duplicate rank assignments.
    # 
    # SQLite transaction modes:
    # - BEGIN (DEFERRED): Lock acquired on first write (too late for our use case)
    # - BEGIN IMMEDIATE: Reserved lock acquired immediately, prevents other writers
    # - BEGIN EXCLUSIVE: Exclusive lock, prevents all access (too restrictive)
    #
    # With BEGIN IMMEDIATE:
    # - Transaction 1: BEGIN IMMEDIATE (acquires lock) → SELECT max_rank → INSERT
    # - Transaction 2: BEGIN IMMEDIATE (waits for lock) → SELECT max_rank (sees updated value) → INSERT
    # This ensures the "read max_rank → calculate new_rank → insert" sequence is atomic.
    try:
        cursor.execute("BEGIN IMMEDIATE")
        
        # Track max rank per list_key within the transaction for unranked appends
        # This ensures sequential rank assignment when appending multiple items
        max_rank_cache: Dict[str, int] = {}  # list_key -> current_max_rank
        
        # Process each operation
        for idx, op in enumerate(ops_response.ops, 1):
            try:
                if op.op == "ranked_list_set":
                    # Validate required fields
                    if not op.list_key or not op.value:
                        result.errors.append(
                            f"Operation {idx}: ranked_list_set requires list_key and value"
                        )
                        continue
                    
                    # Extract topic from list_key
                    topic = extract_topic_from_list_key(op.list_key)
                    if not topic:
                        result.errors.append(
                            f"Operation {idx}: Invalid list_key format: {op.list_key}. "
                            "Expected format: user.favorites.<topic>"
                        )
                        continue
                    
                    # Canonicalize topic using Canonicalizer subsystem (defensive - topics should already be canonical)
                    from server.services.canonicalizer import canonicalize_topic
                    canonicalization_result = canonicalize_topic(topic, invoke_teacher=False)  # Don't invoke teacher here - should already be canonical
                    canonical_topic = canonicalization_result.canonical_topic
                    list_key_for_check = canonical_list_key(canonical_topic)
                    
                    # Normalize value for duplicate checking (must happen before duplicate check)
                    normalized_value, _ = normalize_fact_value(op.value, is_ranked_list=True)
                    
                    # RANK ASSIGNMENT: This is the SINGLE SOURCE OF TRUTH for rank assignment
                    # - If rank is None: This is an unranked append, assign rank atomically
                    # - If rank is provided: Use it as-is (explicit user intent)
                    if op.rank is None:
                        # APPEND-MANY SEMANTICS: For unranked appends, always allow append to end
                        # Even if ranked list exists, treat as append-many (not replacement)
                        # DUPLICATE PREVENTION: For favorites topics, check if value already exists
                        # Only block duplicates for unranked appends to favorites (user.favorites.*)
                        # Explicit ranks always allowed (user can explicitly request duplicates)
                        
                        is_favorites_topic = list_key_for_check.startswith("user.favorites.")
                        
                        logger.debug(
                            f"[FACTS-APPLY] Processing unranked append: "
                            f"is_favorites_topic={is_favorites_topic}, "
                            f"list_key={list_key_for_check}, "
                            f"normalized_value='{normalized_value}'"
                        )
                        
                        if is_favorites_topic:
                            # For duplicate checking, use the raw value (not normalized_value from normalize_fact_value)
                            # normalize_favorite_value will handle the normalization for comparison
                            existing_rank = _check_value_exists_in_ranked_list(
                                conn, project_uuid, list_key_for_check, op.value
                            )
                            
                            logger.debug(
                                f"[FACTS-APPLY] Duplicate check result: existing_rank={existing_rank} "
                                f"for value='{op.value}' in topic={canonical_topic}"
                            )
                            
                            if existing_rank is not None:
                                # Value already exists - block duplicate append
                                # Store duplicate info for telemetry and user-facing message
                                result.duplicate_blocked[op.value] = {
                                    "value": op.value,
                                    "existing_rank": existing_rank,
                                    "topic": canonical_topic,
                                    "list_key": list_key_for_check
                                }
                                logger.info(
                                    f"[FACTS-APPLY] Duplicate blocked: '{op.value}' already exists at rank {existing_rank} "
                                    f"for topic={canonical_topic}"
                                )
                                # Skip this operation (don't append)
                                continue
                        
                        # Unranked append: assign rank atomically
                        # For multiple appends in the same transaction, track max_rank within the transaction
                        # to ensure sequential assignment (1, 2, 3, ...) instead of all getting the same rank
                        if list_key_for_check not in max_rank_cache:
                            # First op for this list_key: get initial max_rank from DB
                            max_rank_cache[list_key_for_check] = _get_max_rank_atomic(
                                conn, project_uuid, canonical_topic, list_key_for_check
                            )
                        
                        # Increment max_rank for this op
                        max_rank_cache[list_key_for_check] += 1
                        assigned_rank = max_rank_cache[list_key_for_check]
                        fact_key = canonical_rank_key(canonical_topic, assigned_rank)
                        rank_assignment_source = "atomic_append"
                        logger.info(
                            f"[FACTS-APPLY] Unranked append: assigned rank {assigned_rank} atomically "
                            f"(topic={canonical_topic}, list_key={list_key_for_check})"
                        )
                        
                        # Normalize value for storage
                        normalized_value, warning = normalize_fact_value(op.value, is_ranked_list=True)
                        if warning:
                            result.warnings.append(f"Operation {idx}: {warning}")
                        
                        # Mark previous facts with same fact_key as not current (before inserting new one)
                        cursor.execute("""
                            UPDATE project_facts
                            SET is_current = 0
                            WHERE project_id = ? AND fact_key = ? AND is_current = 1
                        """, (project_uuid, fact_key))
                        
                        # Insert new fact with assigned rank
                        fact_id = str(uuid.uuid4())
                        created_at = datetime.now()
                        cursor.execute("""
                            INSERT INTO project_facts (
                                fact_id, project_id, fact_key, value_text, value_type,
                                confidence, source_message_uuid, created_at, effective_at,
                                supersedes_fact_id, is_current
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                        """, (
                            fact_id, project_uuid, fact_key, normalized_value, "string",
                            op.confidence or 1.0, message_uuid, created_at, created_at, None
                        ))
                        
                        # Track rank assignment source
                        result.rank_assignment_source[fact_key] = rank_assignment_source
                        
                        # Count as store (new fact)
                        result.store_count += 1
                        result.stored_fact_keys.append(fact_key)
                        logger.debug(
                            f"[FACTS-APPLY] ✅ APPEND op {idx}: '{op.value}' at rank {assigned_rank} "
                            f"(topic={canonical_topic})"
                        )
                    else:
                        # Explicit rank provided: use ranked mutation logic (MOVE, INSERT, or NO-OP)
                        # CRITICAL: Final rank override from user text (#N) - router/LLM can't break it
                        # Extract rank directly from the operation's context if available
                        # This ensures "#2 favorite" always results in rank 2, never rank 1
                        desired_rank = op.rank
                        rank_assignment_source = "explicit"
                        
                        # Final safety check: if rank is 1 but we're in a mutation context, verify it's intentional
                        # (This is a defensive check - the real fix is in facts_persistence.py rank extraction)
                        if desired_rank == 1:
                            logger.debug(
                                f"[FACTS-APPLY] Rank mutation with rank=1 for '{op.value}'. "
                                f"This should only happen if user explicitly said '#1' or 'first'."
                            )
                        
                        logger.info(
                            f"[FACTS-E2E] RANK-MUTATION: topic={canonical_topic!r} desired_rank={desired_rank} "
                            f"value={op.value!r} list_key={list_key_for_check!r}"
                        )
                        
                        # Normalize value for storage (already normalized above for duplicate checking)
                        normalized_value, warning = normalize_fact_value(op.value, is_ranked_list=True)
                        if warning:
                            result.warnings.append(f"Operation {idx}: {warning}")
                        
                        # Apply ranked mutation (MOVE, INSERT, or NO-OP)
                        mutation_result = _apply_ranked_mutation(
                            conn=conn,
                            cursor=cursor,
                            project_uuid=project_uuid,
                            canonical_topic=canonical_topic,
                            list_key=list_key_for_check,
                            desired_rank=desired_rank,
                            value=op.value,  # Raw value for logging/comparison
                            message_uuid=message_uuid,
                            normalized_value=normalized_value  # Normalized value for storage
                        )
                        
                        # Handle mutation result
                        fact_key = canonical_rank_key(canonical_topic, mutation_result["new_rank"])
                        result.rank_assignment_source[fact_key] = rank_assignment_source
                        
                        # Store mutation info for UI messaging
                        result.rank_mutations[fact_key] = {
                            "action": mutation_result["action"],
                            "old_rank": mutation_result.get("old_rank"),
                            "new_rank": mutation_result["new_rank"],
                            "value": op.value,
                            "topic": canonical_topic
                        }
                        
                        if mutation_result["action"] == "noop":
                            # Value already at desired rank: NO-OP
                            logger.info(
                                f"[FACTS-APPLY] Rank mutation NO-OP: '{op.value}' already at rank {desired_rank} "
                                f"for topic={canonical_topic}"
                            )
                            # Don't increment store_count or update_count for NO-OP
                        else:
                            # MOVE, INSERT, or APPEND: fact was created
                            # Count shifted items as updates
                            result.update_count += len(mutation_result["shifted_items"])
                            
                            # Count the main operation
                            if mutation_result["action"] == "move":
                                result.update_count += 1  # MOVE is an update
                                logger.debug(
                                    f"[FACTS-APPLY] ✅ MOVE op {idx}: '{op.value}' from rank {mutation_result['old_rank']} "
                                    f"to {mutation_result['new_rank']} (topic={canonical_topic})"
                                )
                            elif mutation_result["action"] == "insert":
                                result.store_count += 1  # INSERT is a new store
                                logger.debug(
                                    f"[FACTS-APPLY] ✅ INSERT op {idx}: '{op.value}' at rank {mutation_result['new_rank']} "
                                    f"(topic={canonical_topic})"
                                )
                            elif mutation_result["action"] == "append":
                                result.store_count += 1  # APPEND is a new store
                                logger.debug(
                                    f"[FACTS-APPLY] ✅ APPEND op {idx}: '{op.value}' at rank {mutation_result['new_rank']} "
                                    f"(topic={canonical_topic})"
                                )
                            
                            result.stored_fact_keys.append(fact_key)
                            
                            # Add shifted fact keys to stored_fact_keys
                            for old_rank, new_rank, shifted_value in mutation_result["shifted_items"]:
                                shifted_fact_key = canonical_rank_key(canonical_topic, new_rank)
                                result.stored_fact_keys.append(shifted_fact_key)
                
                elif op.op == "set":
                    # Validate required fields
                    if not op.fact_key or not op.value:
                        result.errors.append(
                            f"Operation {idx}: set requires fact_key and value"
                        )
                        continue
                    
                    # Normalize key and value
                    normalized_key, key_warning = normalize_fact_key(op.fact_key)
                    if key_warning:
                        result.warnings.append(f"Operation {idx}: {key_warning}")
                    
                    normalized_value, value_warning = normalize_fact_value(op.value, is_ranked_list=False)
                    if value_warning:
                        result.warnings.append(f"Operation {idx}: {value_warning}")
                    
                    # Store fact atomically within the transaction
                    fact_id = str(uuid.uuid4())
                    created_at = datetime.now()
                    effective_at = created_at
                    
                    # Check if fact_key already exists
                    cursor.execute("""
                        SELECT fact_id, value_text FROM project_facts
                        WHERE project_id = ? AND fact_key = ? AND is_current = 1
                        ORDER BY effective_at DESC, created_at DESC
                        LIMIT 1
                    """, (project_uuid, normalized_key))
                    previous_fact = cursor.fetchone()
                    supersedes_fact_id = previous_fact[0] if previous_fact else None
                    
                    # Determine action type
                    action_type = "store"
                    if previous_fact:
                        previous_value = previous_fact[1] if len(previous_fact) > 1 else None
                        if previous_value and previous_value != normalized_value:
                            action_type = "update"
                    
                    # Mark previous facts as not current
                    if previous_fact:
                        cursor.execute("""
                            UPDATE project_facts
                            SET is_current = 0
                            WHERE project_id = ? AND fact_key = ? AND is_current = 1
                        """, (project_uuid, normalized_key))
                    
                    # Insert new fact
                    cursor.execute("""
                        INSERT INTO project_facts (
                            fact_id, project_id, fact_key, value_text, value_type,
                            confidence, source_message_uuid, created_at, effective_at,
                            supersedes_fact_id, is_current
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """, (
                        fact_id, project_uuid, normalized_key, normalized_value, "string",
                        op.confidence or 1.0, message_uuid, created_at, effective_at,
                        supersedes_fact_id
                    ))
                    
                    # Count based on action type
                    if action_type == "store":
                        result.store_count += 1
                        logger.debug(f"[FACTS-APPLY] ✅ STORE op {idx}: {normalized_key} = {normalized_value}")
                    elif action_type == "update":
                        result.update_count += 1
                        logger.debug(f"[FACTS-APPLY] ✅ UPDATE op {idx}: {normalized_key} = {normalized_value}")
                    
                    result.stored_fact_keys.append(normalized_key)
                
                elif op.op == "ranked_list_clear":
                    # Clear all ranks for a list_key
                    if not op.list_key:
                        result.errors.append(
                            f"Operation {idx}: ranked_list_clear requires list_key"
                        )
                        continue
                    
                    # Extract topic
                    topic = extract_topic_from_list_key(op.list_key)
                    if not topic:
                        result.errors.append(
                            f"Operation {idx}: Invalid list_key format: {op.list_key}"
                        )
                        continue
                    
                    # Query all current facts for this list_key prefix
                    # This is a special operation - we need to mark all ranks as not current
                    # For now, we'll implement this by querying and updating
                    # TODO: Consider adding a bulk clear operation to DB
                    logger.warning(f"[FACTS-APPLY] ranked_list_clear not yet fully implemented for {op.list_key}")
                    result.warnings.append(f"Operation {idx}: ranked_list_clear is not yet implemented")
                
                else:
                    result.errors.append(f"Operation {idx}: Unknown operation type: {op.op}")
                    
            except Exception as e:
                error_msg = f"Operation {idx}: Failed to apply {op.op}: {e}"
                result.errors.append(error_msg)
                logger.error(f"[FACTS-APPLY] {error_msg}", exc_info=True)
        
        # RANKED-LIST INVARIANT VALIDATION: Run after all ops but before commit
        # Group operations by list_key to validate each ranked list
        ranked_lists_to_validate: Dict[str, str] = {}  # list_key -> canonical_topic
        
        # Collect all list_keys that were modified
        for op in ops_response.ops:
            if op.op == "ranked_list_set" and op.list_key:
                topic = extract_topic_from_list_key(op.list_key)
                if topic:
                    from server.services.canonicalizer import canonicalize_topic
                    canonicalization_result = canonicalize_topic(topic, invoke_teacher=False)
                    canonical_topic = canonicalization_result.canonical_topic
                    list_key_for_validation = canonical_list_key(canonical_topic)
                    ranked_lists_to_validate[list_key_for_validation] = canonical_topic
        
        # Validate each ranked list
        for list_key_to_validate, canonical_topic in ranked_lists_to_validate.items():
            items = _get_ranked_list_items(conn, project_uuid, list_key_to_validate)
            if items:
                is_valid, error_msg = validate_ranked_list_invariants(items, list_key_to_validate)
                if not is_valid:
                    # Invariant violation - prevent commit
                    logger.error(
                        f"[FACTS-APPLY] ❌ Ranked list invariant violation for '{list_key_to_validate}': {error_msg}"
                    )
                    result.errors.append(
                        f"Ranked list invariant violation for {canonical_topic}: {error_msg}"
                    )
                    # Rollback transaction
                    cursor.execute("ROLLBACK")
                    conn.rollback()
                    conn.close()
                    return result
        
        # Commit transaction
        cursor.execute("COMMIT")
        conn.commit()
        
    except Exception as e:
        # Rollback on error
        try:
            cursor.execute("ROLLBACK")
            conn.rollback()
        except:
            pass
        logger.error(f"[FACTS-APPLY] Transaction failed, rolled back: {e}", exc_info=True)
        result.errors.append(f"Transaction failed: {e}")
    finally:
        conn.close()
    
    logger.info(
        f"[FACTS-E2E] APPLY: store_count={result.store_count} update_count={result.update_count} "
        f"dupes={len(result.duplicate_blocked)} errors={len(result.errors)} "
        f"invariant_ok={len(result.errors) == 0} message_uuid={message_uuid}"
    )
    
    logger.info(
        f"[FACTS-APPLY] ✅ Applied operations: S={result.store_count} U={result.update_count} "
        f"keys={len(result.stored_fact_keys)} errors={len(result.errors)}"
    )
    
    return result

