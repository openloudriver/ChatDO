"""
Deterministic Facts Operations Applier.

This is the SINGLE SOURCE OF TRUTH for all fact writes.
No other code path should write facts to the database.
"""
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from server.contracts.facts_ops import FactsOp, FactsOpsResponse
from server.services.facts_normalize import (
    normalize_fact_key,
    normalize_fact_value,
    canonical_rank_key,
    extract_topic_from_list_key
)
from server.services.projects.project_resolver import validate_project_uuid
from memory_service.memory_dashboard import db

logger = logging.getLogger(__name__)


@dataclass
class ApplyResult:
    """Result of applying facts operations."""
    store_count: int = 0
    update_count: int = 0
    stored_fact_keys: List[str] = None
    warnings: List[str] = None
    errors: List[str] = None
    
    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.stored_fact_keys is None:
            self.stored_fact_keys = []
        if self.warnings is None:
            self.warnings = []
        if self.errors is None:
            self.errors = []


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
    
    # Process each operation
    for idx, op in enumerate(ops_response.ops, 1):
        try:
            if op.op == "ranked_list_set":
                # Validate required fields
                if not op.list_key or op.rank is None or not op.value:
                    result.errors.append(
                        f"Operation {idx}: ranked_list_set requires list_key, rank, and value"
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
                
                # Canonicalize topic (ensures consistent normalization)
                from server.services.facts_topic import canonicalize_topic
                canonical_topic = canonicalize_topic(topic)
                
                # Build canonical fact_key using canonicalized topic
                fact_key = canonical_rank_key(canonical_topic, op.rank)
                
                # Normalize value (ranked list values have stricter length limit)
                normalized_value, warning = normalize_fact_value(op.value, is_ranked_list=True)
                if warning:
                    result.warnings.append(f"Operation {idx}: {warning}")
                
                # Store fact
                fact_id, action_type = db.store_project_fact(
                    project_id=project_uuid,
                    fact_key=fact_key,
                    value_text=normalized_value,
                    value_type="string",
                    source_message_uuid=message_uuid,
                    confidence=op.confidence or 1.0,
                    source_id=source_id
                )
                
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
                
                # Store fact
                fact_id, action_type = db.store_project_fact(
                    project_id=project_uuid,
                    fact_key=normalized_key,
                    value_text=normalized_value,
                    value_type="string",
                    source_message_uuid=message_uuid,
                    confidence=op.confidence or 1.0,
                    source_id=source_id
                )
                
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
    
    logger.info(
        f"[FACTS-APPLY] ✅ Applied operations: S={result.store_count} U={result.update_count} "
        f"keys={len(result.stored_fact_keys)} errors={len(result.errors)}"
    )
    
    return result

