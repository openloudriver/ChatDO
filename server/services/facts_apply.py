"""
Deterministic Facts Operations Applier.

This is the SINGLE SOURCE OF TRUTH for all fact writes.
No other code path should write facts to the database.
"""
import logging
import uuid
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
        value: Value to check for (normalized)
        
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
    
    for row in rows:
        fact_key = row[0]
        existing_value = row[1] if len(row) > 1 else ""
        
        # Normalize both values using the same normalization function for accurate comparison
        # This ensures we compare normalized values consistently (handles spaces, quotes, etc.)
        from server.services.facts_normalize import normalize_fact_value
        normalized_existing, _ = normalize_fact_value(existing_value, is_ranked_list=True)
        normalized_input, _ = normalize_fact_value(value, is_ranked_list=True)
        
        logger.debug(
            f"[FACTS-APPLY] Comparing: existing='{existing_value}' (norm: '{normalized_existing}') "
            f"vs input='{value}' (norm: '{normalized_input}') -> "
            f"match={normalized_existing.strip().lower() == normalized_input.strip().lower()}"
        )
        
        # Compare normalized values (case-insensitive, trimmed, spaces collapsed, etc.)
        if normalized_existing and normalized_existing.strip().lower() == normalized_input.strip().lower():
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
    
    logger.info(f"[FACTS-APPLY] Applying {len(ops_response.ops)} operations for project {project_uuid}")
    
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
                        # DUPLICATE PREVENTION: For favorites topics, check if value already exists
                        # Only block duplicates for unranked appends to favorites (user.favorites.*)
                        # Explicit ranks always allowed (user can explicitly request duplicates)
                        is_favorites_topic = list_key_for_check.startswith("user.favorites.")
                        
                        logger.debug(
                            f"[FACTS-APPLY] Checking duplicate prevention: "
                            f"is_favorites_topic={is_favorites_topic}, "
                            f"list_key={list_key_for_check}, "
                            f"normalized_value='{normalized_value}'"
                        )
                        
                        if is_favorites_topic:
                            existing_rank = _check_value_exists_in_ranked_list(
                                conn, project_uuid, list_key_for_check, normalized_value
                            )
                            
                            logger.debug(
                                f"[FACTS-APPLY] Duplicate check result: existing_rank={existing_rank} "
                                f"for value='{normalized_value}' in topic={canonical_topic}"
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
                        
                        # Unranked append: assign rank atomically using _get_max_rank_atomic()
                        # This ensures atomicity and prevents race conditions
                        max_rank = _get_max_rank_atomic(conn, project_uuid, canonical_topic, list_key_for_check)
                        assigned_rank = max_rank + 1
                        fact_key = canonical_rank_key(canonical_topic, assigned_rank)
                        rank_assignment_source = "atomic_append"
                        logger.info(
                            f"[FACTS-APPLY] Unranked append: assigned rank {assigned_rank} atomically "
                            f"(max_rank={max_rank}, topic={canonical_topic})"
                        )
                    else:
                        # Explicit rank provided: use it as-is (allows duplicates if user explicitly requests)
                        assigned_rank = op.rank
                        fact_key = canonical_rank_key(canonical_topic, assigned_rank)
                        rank_assignment_source = "explicit"
                        logger.debug(f"[FACTS-APPLY] Explicit rank: using rank {assigned_rank} for topic={canonical_topic}")
                    
                    # Store rank assignment source for telemetry
                    result.rank_assignment_source[fact_key] = rank_assignment_source
                
                    # BACKWARD COMPATIBILITY: Check for legacy scalar facts and migrate them
                    # Look for user.favorites.<topic> (without rank) before writing ranked entry
                    try:
                        scalar_key = op.list_key  # e.g., "user.favorites.crypto" (without .1, .2, etc.)
                        cursor.execute("""
                            SELECT fact_id, value_text, source_message_uuid, created_at
                            FROM project_facts
                            WHERE project_id = ? AND fact_key = ? AND is_current = 1
                            ORDER BY effective_at DESC, created_at DESC
                            LIMIT 1
                        """, (project_uuid, scalar_key))
                        scalar_fact = cursor.fetchone()
                        
                        if scalar_fact:
                            # Legacy scalar fact found - migrate to ranked entry at rank 1
                            legacy_value = scalar_fact[1] if len(scalar_fact) > 1 else ""
                            legacy_message_uuid = scalar_fact[2] if len(scalar_fact) > 2 else None
                            legacy_created_at = scalar_fact[3] if len(scalar_fact) > 3 else None
                            
                            if legacy_value:
                                # Create ranked entry at rank 1 from legacy scalar
                                legacy_rank_key = canonical_rank_key(canonical_topic, 1)
                                
                                logger.info(
                                    f"[FACTS-APPLY] Migrating legacy scalar fact: {scalar_key} = {legacy_value} "
                                    f"→ ranked entry at {legacy_rank_key}"
                                )
                                
                                # Store as ranked entry within the same transaction
                                # Use the same connection for atomicity
                                legacy_fact_id = str(uuid.uuid4())
                                legacy_created_at_dt = legacy_created_at if legacy_created_at else datetime.now()
                                
                                # Mark scalar as not current
                                cursor.execute("""
                                    UPDATE project_facts
                                    SET is_current = 0
                                    WHERE project_id = ? AND fact_key = ? AND is_current = 1
                                """, (project_uuid, scalar_key))
                                
                                # Insert ranked entry
                                cursor.execute("""
                                    INSERT INTO project_facts (
                                        fact_id, project_id, fact_key, value_text, value_type,
                                        confidence, source_message_uuid, created_at, effective_at,
                                        supersedes_fact_id, is_current
                                    )
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                                """, (
                                    legacy_fact_id, project_uuid, legacy_rank_key, legacy_value, "string",
                                    1.0, legacy_message_uuid or message_uuid, legacy_created_at_dt, legacy_created_at_dt,
                                    None
                                ))
                    except Exception as e:
                        logger.warning(f"[FACTS-APPLY] Failed to check/migrate legacy scalar facts: {e}")
                        # Continue with normal ranked_list_set processing
                
                    # Value already normalized above for duplicate checking
                    # Just check for warnings (normalization already done)
                    _, warning = normalize_fact_value(op.value, is_ranked_list=True)
                    if warning:
                        result.warnings.append(f"Operation {idx}: {warning}")
                    
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
                    """, (project_uuid, fact_key))
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
                        """, (project_uuid, fact_key))
                    
                    # Insert new fact
                    cursor.execute("""
                        INSERT INTO project_facts (
                            fact_id, project_id, fact_key, value_text, value_type,
                            confidence, source_message_uuid, created_at, effective_at,
                            supersedes_fact_id, is_current
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """, (
                        fact_id, project_uuid, fact_key, normalized_value, "string",
                        op.confidence or 1.0, message_uuid, created_at, effective_at,
                        supersedes_fact_id
                    ))
                    
                    # Count based on action type
                    if action_type == "store":
                        result.store_count += 1
                        logger.debug(f"[FACTS-APPLY] ✅ STORE op {idx}: {fact_key} = {normalized_value}")
                    elif action_type == "update":
                        result.update_count += 1
                        logger.debug(f"[FACTS-APPLY] ✅ UPDATE op {idx}: {fact_key} = {normalized_value}")
                    
                    result.stored_fact_keys.append(fact_key)
                
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
        f"[FACTS-APPLY] ✅ Applied operations: S={result.store_count} U={result.update_count} "
        f"keys={len(result.stored_fact_keys)} errors={len(result.errors)}"
    )
    
    return result

