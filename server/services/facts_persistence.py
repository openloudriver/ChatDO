"""
Synchronous Facts persistence module.

This module provides a direct, synchronous path for storing facts that does NOT
depend on the Memory Service indexing pipeline. Facts are stored immediately
and deterministically, ensuring Facts-S/U counts are always truthful.

Facts DB contract: project_facts.project_id must always be the project UUID string.
Never use project name/slug for DB access.

NEW ARCHITECTURE: Uses GPT-5 Nano routing plan candidates when available to avoid double Nano calls.
Falls back to GPT-5 Nano Facts extractor only when candidate is not available.
"""
import logging
import json
from typing import Dict, Optional, Tuple, List, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# In-memory store for raw LLM responses (keyed by message_uuid) for quick inspection
_raw_llm_responses: Dict[str, Dict[str, Any]] = {}


# REMOVED: resolve_ranked_list_topic() - Legacy function no longer used
# Topic resolution for ranked lists is now handled by GPT-5 Nano LLM in the Facts extraction prompt
# This ensures all Facts behavior goes through the unified GPT-5 Nano → JSON ops → deterministic apply path


def get_or_create_message_uuid(
    project_id: str,
    chat_id: str,
    message_id: str,
    role: str,
    content: str,
    timestamp: datetime,
    message_index: int,
    provided_message_uuid: Optional[str] = None  # Client-provided UUID to use
) -> Optional[str]:
    """
    Get or create message_uuid for a message.
    
    This ensures we have a message_uuid before storing facts, even if
    the Memory Service is unavailable.
    
    If provided_message_uuid is given, it will be used (idempotent: if message
    already exists with different UUID, existing UUID is preserved).
    
    Args:
        project_id: Project ID
        chat_id: Chat ID
        message_id: Message ID
        role: Message role
        content: Message content
        timestamp: Message timestamp
        message_index: Message index in conversation
        provided_message_uuid: Optional client-provided UUID to use
        
    Returns:
        message_uuid if successful, None otherwise
    """
    try:
        from memory_service.memory_dashboard import db
        
        source_id = f"project-{project_id}"
        db.init_db(source_id, project_id=project_id)
        
        # Upsert source (chat messages don't have a root_path)
        db.upsert_source(source_id, project_id, "", None, None)
        
        # Upsert chat message (uses provided_message_uuid if given, otherwise generates)
        chat_message_id = db.upsert_chat_message(
            source_id=source_id,
            project_id=project_id,
            chat_id=chat_id,
            message_id=message_id,
            role=role,
            content=content,
            timestamp=timestamp,
            message_index=message_index,
            message_uuid=provided_message_uuid  # Pass provided UUID
        )
        
        # Get the message_uuid
        chat_message = db.get_chat_message_by_id(chat_message_id, source_id)
        message_uuid = chat_message.message_uuid if chat_message else None
        
        if message_uuid:
            logger.debug(f"[FACTS-PERSIST] Got message_uuid={message_uuid} for message {message_id}")
        else:
            logger.warning(f"[FACTS-PERSIST] ⚠️ message_uuid is None after upsert for message {message_id}")
        
        return message_uuid
        
    except Exception as e:
        logger.error(f"[FACTS-PERSIST] ❌ Failed to get/create message_uuid: {e}", exc_info=True)
        return None


def _convert_routing_candidate_to_ops(
    candidate: Any,  # FactsWriteCandidate from RoutingPlan
    project_id: Optional[str] = None,  # Project ID for checking existing ranks
    user_message: Optional[str] = None  # Original user message for fallback rank detection
) -> Tuple[Any, Any]:  # (FactsOpsResponse, CanonicalizationResult)
    """
    Convert RoutingPlan.facts_write_candidate to FactsOpsResponse.
    
    This avoids the second Nano call for Facts extraction when the router
    already extracted the fact candidate.
    
    Uses Canonicalizer subsystem for topic canonicalization.
    
    UNBOUNDED RANKED MODEL:
    - If rank_ordered=True: Use ranks 1, 2, 3... (explicit ordering)
    - If rank_ordered=False: Append after max(rank) (FIFO append)
    - Never overwrite existing entries unless explicitly updating a specific rank
    
    Args:
        candidate: FactsWriteCandidate from RoutingPlan
        project_id: Optional project ID to check existing max rank for unranked writes
        
    Returns:
        Tuple of (FactsOpsResponse, CanonicalizationResult)
        
    Raises:
        Exception: If canonicalization fails or other critical errors occur
    """
    from server.contracts.facts_ops import FactsOp, FactsOpsResponse
    from server.services.canonicalizer import canonicalize_topic
    from server.services.facts_normalize import canonical_list_key
    
    ops = []
    canonicalization_result = None
    
    try:
        # Canonicalize topic using Canonicalizer subsystem
        # ERROR HANDLING: Wrap in try/except for Facts-F diagnostics
        try:
            canonicalization_result = canonicalize_topic(candidate.topic, invoke_teacher=True)
            canonical_topic = canonicalization_result.canonical_topic
        except Exception as e:
            logger.error(f"[FACTS-PERSIST] ❌ Canonicalization failed for topic '{candidate.topic}': {e}", exc_info=True)
            # Return empty ops with error indication
            return FactsOpsResponse(ops=[], needs_clarification=[f"Failed to canonicalize topic: {e}"]), None
        
        try:
            list_key = canonical_list_key(canonical_topic)
        except Exception as e:
            logger.error(f"[FACTS-PERSIST] ❌ Failed to build list_key for topic '{canonical_topic}': {e}", exc_info=True)
            return FactsOpsResponse(ops=[], needs_clarification=[f"Failed to build list key: {e}"]), canonicalization_result
        
        # Handle single value or list of values
        try:
            values = candidate.value if isinstance(candidate.value, list) else [candidate.value]
        except Exception as e:
            logger.error(f"[FACTS-PERSIST] ❌ Failed to process candidate values: {e}", exc_info=True)
            return FactsOpsResponse(ops=[], needs_clarification=[f"Failed to process values: {e}"]), canonicalization_result
        
        # Determine rank assignment based on explicit rank or rank_ordered flag
        # Priority: explicit rank (candidate.rank) > fallback detection > rank_ordered sequential > unranked append
        explicit_rank = None
        if hasattr(candidate, 'rank') and candidate.rank is not None:
            # Router extracted explicit rank
            explicit_rank = candidate.rank
        elif user_message:
            # Fallback: detect rank from user message if router didn't extract it
            from server.services.ordinal_detection import detect_ordinal_rank
            detected_rank = detect_ordinal_rank(user_message)
            if detected_rank is not None:
                explicit_rank = detected_rank
                logger.info(
                    f"[FACTS-PERSIST] Router didn't extract rank, but detected rank {explicit_rank} "
                    f"from user message: '{user_message}'"
                )
        
        if explicit_rank is not None:
            # User specified an explicit rank (e.g., "#4 favorite planet is Venus")
            # Use that exact rank for the value(s)
            current_rank = explicit_rank
            for value in values:
                ops.append(FactsOp(
                    op="ranked_list_set",
                    list_key=list_key,
                    rank=current_rank,  # Use explicit rank from user
                    value=str(value),
                    confidence=1.0
                ))
                # If multiple values with explicit rank, increment for each (e.g., "#4 favorite planets are Venus, Mars" → rank 4, 5)
                current_rank += 1
        elif candidate.rank_ordered:
            # RANKED-MODE PROTECTION: Check if ranked list already exists
            # If it does, reject unranked bulk writes (require explicit ranks)
            from memory_service.memory_dashboard import db
            from server.services.facts_apply import _check_ranked_list_exists
            
            # Check if ranked list exists (must be done outside transaction, so use a read-only check)
            # We'll do a full check in apply_facts_ops() within the transaction, but this is a pre-check
            ranked_list_exists = False
            if project_id:
                try:
                    source_id = f"project-{project_id}"
                    db.init_db(source_id, project_id=project_id)
                    conn = db.get_db_connection(source_id, project_id=project_id)
                    ranked_list_exists = _check_ranked_list_exists(conn, project_id, list_key)
                    conn.close()
                except Exception as e:
                    logger.warning(f"[FACTS-PERSIST] Could not check ranked list existence: {e}")
                    # Continue - will be checked again in apply_facts_ops() within transaction
            
            if ranked_list_exists:
                # Ranked list exists - reject unranked bulk write
                logger.warning(
                    f"[FACTS-PERSIST] Rejecting unranked bulk write to existing ranked list: "
                    f"topic={canonical_topic}, list_key={list_key}. "
                    f"User must specify explicit ranks (e.g., 'My #1 favorite X is Y')."
                )
                return FactsOpsResponse(
                    ops=[],
                    needs_clarification=[
                        f"You already have a ranked list for {canonical_topic}. "
                        f"To update it, please specify explicit ranks (e.g., 'My #1 favorite {canonical_topic} is X', "
                        f"'My #2 favorite {canonical_topic} is Y'). "
                        f"Bulk updates like 'My favorite {canonical_topic} are X, Y, Z' are not allowed once a ranked list exists."
                    ]
                ), canonicalization_result
            
            # No ranked list exists - allow bulk write with sequential ranks
            # Explicit ordering: use ranks 1, 2, 3... (may overwrite existing ranks)
            # Rank is assigned here (explicit user intent for multiple values)
            start_rank = 1
            for offset, value in enumerate(values):
                rank = start_rank + offset
                ops.append(FactsOp(
                    op="ranked_list_set",
                    list_key=list_key,
                    rank=rank,  # Explicit rank assigned sequentially
                    value=str(value),
                    confidence=1.0
                ))
        else:
            # Unranked/FIFO append: emit operations with rank=None
            # Rank will be assigned atomically in apply_facts_ops() using _get_max_rank_atomic()
            # This centralizes rank assignment logic and avoids edge cases with pre-check limits
            for value in values:
                ops.append(FactsOp(
                    op="ranked_list_set",
                    list_key=list_key,
                    rank=None,  # None = append operation, rank assigned atomically in apply_facts_ops()
                    value=str(value),
                    confidence=1.0
                ))
        
        ops_response = FactsOpsResponse(
            ops=ops,
            needs_clarification=[]
        )
        
        return ops_response, canonicalization_result
        
    except Exception as e:
        # Catch-all for any unexpected errors
        logger.error(f"[FACTS-PERSIST] ❌ Unexpected error in _convert_routing_candidate_to_ops: {e}", exc_info=True)
        # Return empty ops with error indication
        return FactsOpsResponse(ops=[], needs_clarification=[f"Unexpected error: {e}"]), canonicalization_result


async def persist_facts_synchronously(
    project_id: str,
    message_content: str,
    role: str,
    message_uuid: Optional[str] = None,
    chat_id: Optional[str] = None,
    message_id: Optional[str] = None,
    timestamp: Optional[datetime] = None,
    message_index: Optional[int] = None,
    source_id: Optional[str] = None,
    retrieved_facts: Optional[List[Dict]] = None,  # For schema-hint topic resolution
    write_intent_detected: bool = False,  # Flag to enable enhanced diagnostics
    routing_plan_candidate: Optional[Any] = None  # FactsWriteCandidate from RoutingPlan
) -> Tuple[int, int, list, Optional[str], Optional[List[str]], Optional[Any], Optional[Dict[str, str]], Optional[Dict[str, Dict[str, Any]]]]:
    """
    Extract and store facts synchronously, returning actual store/update counts.
    
    This function:
    - Gets or creates message_uuid if not provided
    - Extracts facts from the message
    - Stores each fact directly via store_project_fact()
    - Returns actual counts based on DB write results
    
    Args:
        project_id: Project ID
        message_content: Message content to extract facts from
        role: Message role ("user" or "assistant")
        message_uuid: Optional UUID of the message (will be created if not provided)
        chat_id: Optional chat ID (required if message_uuid not provided)
        message_id: Optional message ID (required if message_uuid not provided)
        timestamp: Optional message timestamp (required if message_uuid not provided)
        message_index: Optional message index (required if message_uuid not provided)
        source_id: Optional source ID (uses project-based source if not provided)
        
    Returns:
        Tuple of (store_count, update_count, stored_fact_keys, message_uuid, ambiguous_topics, canonicalization_result, rank_assignment_source, duplicate_blocked):
        - store_count: Number of facts actually stored (new facts)
        - update_count: Number of facts actually updated (existing facts with changed values)
        - stored_fact_keys: List of fact keys that were stored/updated
        - message_uuid: The message_uuid used for fact storage (for exclusion in Facts-R)
        - ambiguous_topics: List of candidate topics if ranked list topic is ambiguous, None otherwise
        - canonicalization_result: CanonicalizationResult for telemetry (None if not available)
        - rank_assignment_source: Dict mapping fact_key -> "explicit" | "atomic_append" (None if no ranked facts)
        - duplicate_blocked: Dict mapping value -> {"value": str, "existing_rank": int, "topic": str, "list_key": str} (None if no duplicates blocked)
    """
    store_count = 0
    update_count = 0
    stored_fact_keys = []
    rank_assignment_source = None  # Will be set from apply_result
    duplicate_blocked = None  # Will be set from apply_result
    
    ambiguous_topics = None  # Will be set if ranked list topic resolution is ambiguous
    
    # Initialize variables that may be referenced in diagnostic logging
    # These must be initialized before any branching to ensure they're always in scope
    llm_response = None
    prompt = None
    
    if not project_id:
        logger.warning(f"[FACTS-PERSIST] Skipping fact persistence: project_id is missing")
        return store_count, update_count, stored_fact_keys, None, None, None, None, None
    
    # Enforce Facts DB contract: project_id must be UUID
    from server.services.projects.project_resolver import validate_project_uuid
    try:
        validate_project_uuid(project_id)
    except ValueError as e:
        logger.error(f"[FACTS-PERSIST] ❌ Invalid project_id format: {e}")
        raise ValueError(f"Cannot persist facts: {e}") from e
    
    # Get or create message_uuid if not provided
    if not message_uuid:
        if not all([chat_id, message_id, timestamp is not None, message_index is not None]):
            logger.warning(f"[FACTS-PERSIST] Cannot create message_uuid: missing required params")
            return store_count, update_count, stored_fact_keys, None, None, None, None, None, None
        
        message_uuid = get_or_create_message_uuid(
            project_id=project_id,
            chat_id=chat_id,
            message_id=message_id,
            role=role,
            content=message_content,
            timestamp=timestamp,
            message_index=message_index,
            provided_message_uuid=message_uuid  # Pass provided UUID if available
        )
        
        if not message_uuid:
            logger.warning(f"[FACTS-PERSIST] Failed to get/create message_uuid, skipping fact persistence")
            return store_count, update_count, stored_fact_keys, None, None, None, None, None, None
    
    # Only extract facts from user messages
    if role != "user":
        logger.debug(f"[FACTS-PERSIST] Skipping fact extraction for role={role} (only user messages)")
        return store_count, update_count, stored_fact_keys, message_uuid, None, None, None, None, None
    
    # NEW ARCHITECTURE: Use routing plan candidate if available, otherwise call Facts LLM
    from server.contracts.facts_ops import FactsOpsResponse
    from server.services.facts_apply import apply_facts_ops
    
    ops_response = None
    canonicalization_result = None  # For telemetry
    
    # If routing plan candidate is available, use it directly (no second Nano call)
    if routing_plan_candidate:
        logger.info(
            f"[FACTS-PERSIST] Using routing plan candidate (topic={routing_plan_candidate.topic}, "
            f"value={routing_plan_candidate.value}), skipping Facts LLM call"
        )
        try:
            ops_response, canonicalization_result = _convert_routing_candidate_to_ops(
                routing_plan_candidate,
                project_id=project_id,  # Pass project_id for checking existing max rank
                user_message=message_content  # Pass user message for fallback rank detection
            )
            logger.info(
                f"[FACTS-PERSIST] Canonicalized topic: '{routing_plan_candidate.topic}' → "
                f"'{canonicalization_result.canonical_topic}' "
                f"(confidence: {canonicalization_result.confidence:.3f}, "
                f"source: {canonicalization_result.source}, "
                f"teacher_invoked: {canonicalization_result.teacher_invoked})"
            )
        except Exception as e:
            logger.error(f"[FACTS-PERSIST] Failed to convert routing candidate to ops: {e}", exc_info=True)
            # Fall through to Facts LLM extraction
            ops_response = None
            canonicalization_result = None
    
    # If no candidate or conversion failed, call Facts LLM extractor
    if not ops_response:
        try:
            from server.services.facts_llm.client import (
                run_facts_llm,
                FactsLLMError,
                FactsLLMTimeoutError,
                FactsLLMUnavailableError,
                FactsLLMInvalidJSONError
            )
            from server.services.facts_llm.prompts import build_facts_extraction_prompt
            
            # Build prompt for GPT-5 Nano Facts extractor
            # Convert retrieved_facts to a simple format for prompt
            retrieved_facts_simple = None
            if retrieved_facts:
                retrieved_facts_simple = []
                for fact in retrieved_facts:
                    if isinstance(fact, dict):
                        metadata = fact.get("metadata", {})
                        retrieved_facts_simple.append({
                            "fact_key": metadata.get("fact_key", ""),
                            "value_text": metadata.get("value_text", ""),
                            "metadata": metadata
                        })
            
            prompt = build_facts_extraction_prompt(
                user_message=message_content,
                recent_context=None,  # Could add recent context if needed
                retrieved_facts=retrieved_facts_simple
            )
            
            # Call GPT-5 Nano Facts extractor (hard fail if unavailable)
            # Note: llm_response is already initialized to None at function start
            try:
                logger.debug(f"[FACTS-PERSIST] Calling Facts LLM (GPT-5 Nano) for message (message_uuid={message_uuid})")
                llm_response = await run_facts_llm(prompt)
            except FactsLLMTimeoutError as e:
                # Timeout error
                logger.error(f"[FACTS-PERSIST] ❌ Facts LLM (GPT-5 Nano) timed out: {e}")
                return -1, -1, [], message_uuid, None, None, None, None, None  # Negative counts indicate error
            except FactsLLMUnavailableError as e:
                # Unavailable error
                logger.error(f"[FACTS-PERSIST] ❌ Facts LLM (GPT-5 Nano) unavailable: {e}")
                return -1, -1, [], message_uuid, None, None, None, None, None  # Negative counts indicate error
            except FactsLLMInvalidJSONError as e:
                # Invalid JSON error
                logger.error(f"[FACTS-PERSIST] ❌ Facts LLM returned invalid JSON: {e}")
                return -1, -1, [], message_uuid, None, None, None, None, None  # Negative counts indicate error
            except FactsLLMError as e:
                # Other Facts LLM errors
                logger.error(f"[FACTS-PERSIST] ❌ Facts LLM failed: {e}")
                return -1, -1, [], message_uuid, None, None, None, None, None  # Negative counts indicate error
            
            # Parse JSON response (strict parsing, hard fail if invalid)
            try:
                # Try to extract JSON from markdown code blocks if present
                json_text = llm_response.strip()
                if json_text.startswith("```"):
                    # Extract JSON from code block
                    lines = json_text.split("\n")
                    json_lines = []
                    in_code_block = False
                    for line in lines:
                        if line.strip().startswith("```"):
                            in_code_block = not in_code_block
                            continue
                        if in_code_block:
                            json_lines.append(line)
                    json_text = "\n".join(json_lines).strip()
                
                # Parse JSON
                ops_data = json.loads(json_text)
                ops_response = FactsOpsResponse(**ops_data)
                
                # POST-PROCESS: Detect unranked writes and set rank=None for atomic assignment
                # If Facts LLM extracted rank=1 but user didn't explicitly specify a rank,
                # set rank=None so apply_facts_ops() can assign it atomically
                if ops_response and ops_response.ops:
                    import re
                    # Check if user message explicitly mentions a rank (#1, first, 1st, etc.)
                    explicit_rank_pattern = re.compile(r'\b(#1|first|1st|rank\s*1|number\s*1)\b', re.IGNORECASE)
                    has_explicit_rank = bool(explicit_rank_pattern.search(message_content))
                    
                    for op in ops_response.ops:
                        if op.op == "ranked_list_set" and op.rank == 1 and op.list_key and not has_explicit_rank:
                            # This is likely an unranked write - set rank=None for atomic assignment
                            op.rank = None
                            logger.info(
                                f"[FACTS-PERSIST] Detected unranked write: set rank=None for atomic assignment "
                                f"(topic from list_key={op.list_key})"
                            )
                
            except json.JSONDecodeError as e:
                logger.error(f"[FACTS-PERSIST] ❌ Failed to parse Facts LLM JSON response: {e}")
                logger.error(f"[FACTS-PERSIST] Raw response: {llm_response[:500] if llm_response else 'N/A'}")
                # Hard fail - return error indicator
                return -1, -1, [], message_uuid, None, None, None, None, None
            except Exception as e:
                logger.error(f"[FACTS-PERSIST] ❌ Failed to validate FactsOpsResponse: {e}")
                logger.error(f"[FACTS-PERSIST] Parsed data: {ops_data if 'ops_data' in locals() else 'N/A'}")
                # Hard fail - return error indicator
                return -1, -1, [], message_uuid, None, None, None, None, None
            
            # FORCE EXTRACTION RETRY: If write-intent and ops are empty, retry with stricter prompt
            if write_intent_detected and ops_response and len(ops_response.ops) == 0 and not ops_response.needs_clarification:
                logger.warning(
                    f"[FACTS-PERSIST] ⚠️ Write-intent message but first pass returned empty ops. "
                    f"Retrying with force-extraction prompt (message_uuid={message_uuid})"
                )
                # Build stricter prompt
                from server.services.facts_llm.prompts import build_facts_extraction_prompt_force
                force_prompt = build_facts_extraction_prompt_force(
                    user_message=message_content,
                    retrieved_facts=retrieved_facts_simple
                )
                try:
                    llm_response = await run_facts_llm(force_prompt)
                    # Parse JSON again
                    json_text = llm_response.strip()
                    if json_text.startswith("```"):
                        lines = json_text.split("\n")
                        json_lines = []
                        in_code_block = False
                        for line in lines:
                            if line.strip().startswith("```"):
                                in_code_block = not in_code_block
                                continue
                            if in_code_block:
                                json_lines.append(line)
                        json_text = "\n".join(json_lines).strip()
                    ops_data = json.loads(json_text)
                    ops_response = FactsOpsResponse(**ops_data)
                    logger.info(f"[FACTS-PERSIST] ✅ Force-extraction retry returned {len(ops_response.ops)} ops")
                except Exception as e:
                    logger.error(f"[FACTS-PERSIST] ❌ Force-extraction retry failed: {e}")
                    # Continue with original empty ops - will be logged below
                    pass
        except Exception as e:
            logger.error(f"[FACTS-PERSIST] ❌ Exception during Facts LLM extraction: {e}", exc_info=True)
            # Hard fail on unexpected exceptions
            return -1, -1, [], message_uuid, None, None, None, None
    
    # Check for clarification needed (applies to both routing candidate and LLM paths)
    if ops_response and ops_response.needs_clarification:
        ambiguous_topics = ops_response.needs_clarification
        logger.info(f"[FACTS-PERSIST] Clarification needed: {ambiguous_topics}")
        
        # Store raw response for diagnostics if write-intent
        if write_intent_detected and message_uuid:
            _raw_llm_responses[message_uuid] = {
                "prompt": prompt,
                "raw_response": llm_response,
                "parsed_json": ops_data if 'ops_data' in locals() else None,
                "needs_clarification": ambiguous_topics,
                "ops_count": 0,
                "project_id": project_id,
                "chat_id": chat_id,
                "message_id": message_id
            }
        
        return store_count, update_count, stored_fact_keys, message_uuid, ambiguous_topics, canonicalization_result, None, None, None
    
    # Validate ops_response exists before applying
    if not ops_response:
        logger.error(f"[FACTS-PERSIST] ❌ No ops_response available after conversion/LLM extraction")
        return -1, -1, [], message_uuid, None, None, None, None
    
    # Apply operations deterministically
    apply_result = apply_facts_ops(
        project_uuid=project_id,
        message_uuid=message_uuid,
        ops_response=ops_response,
        source_id=source_id
    )
    
    # Return counts from apply result
    store_count = apply_result.store_count
    update_count = apply_result.update_count
    stored_fact_keys = apply_result.stored_fact_keys
    rank_assignment_source = apply_result.rank_assignment_source if apply_result.rank_assignment_source else None
    duplicate_blocked = apply_result.duplicate_blocked if apply_result.duplicate_blocked else None
    
    # MANDATORY RAW LLM CAPTURE: If write-intent and (S=0, U=0), log full diagnostics
    if write_intent_detected and store_count == 0 and update_count == 0 and message_uuid:
        # Sanitize parsed JSON (remove sensitive data if any)
        sanitized_json = None
        if ops_response:
            sanitized_json = {
                "ops": [{"op": op.op, "list_key": getattr(op, "list_key", None), "fact_key": getattr(op, "fact_key", None)} for op in ops_response.ops],
                "needs_clarification": ops_response.needs_clarification,
                "notes": ops_response.notes
            }
        
        diagnostic_info = {
            "message_uuid": message_uuid,
            "project_id": project_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "prompt": prompt,
            "raw_llm_response": llm_response,
            "parsed_json": sanitized_json,
            "ops_count": len(ops_response.ops) if ops_response else 0,
            "apply_result": {
                "store_count": store_count,
                "update_count": update_count,
                "warnings": apply_result.warnings,
                "errors": apply_result.errors
            }
        }
        
        # Store in memory for quick inspection
        _raw_llm_responses[message_uuid] = diagnostic_info
        
        # Log comprehensive diagnostics
        logger.error(
            f"[FACTS-PERSIST] ❌ DIAGNOSTIC: Write-intent message returned 0 ops. "
            f"message_uuid={message_uuid}, project_id={project_id}, chat_id={chat_id}, "
            f"ops_count={len(ops_response.ops) if ops_response else 0}, "
            f"needs_clarification={ops_response.needs_clarification if ops_response else None}, "
            f"apply_warnings={len(apply_result.warnings)}, apply_errors={len(apply_result.errors)}"
        )
        logger.error(f"[FACTS-PERSIST] Raw LLM response (first 500 chars): {llm_response[:500] if llm_response else 'N/A'}")
        if sanitized_json:
            logger.error(f"[FACTS-PERSIST] Parsed JSON: {json.dumps(sanitized_json, indent=2)}")
    
    # Log warnings/errors
    if apply_result.warnings:
        for warning in apply_result.warnings:
            logger.warning(f"[FACTS-PERSIST] {warning}")
    if apply_result.errors:
        for error in apply_result.errors:
            logger.error(f"[FACTS-PERSIST] {error}")
        # If there are errors, we still return counts but log them
        # The caller can decide if errors should be treated as hard failures
    
    logger.info(
        f"[FACTS-PERSIST] ✅ Persisted facts: S={store_count} U={update_count} "
        f"keys={len(stored_fact_keys)} (message_uuid={message_uuid})"
    )
    
    # Log rank assignment sources for telemetry
    if rank_assignment_source:
        for fact_key, source in rank_assignment_source.items():
            logger.debug(f"[FACTS-PERSIST] Rank assignment: {fact_key} -> {source}")
    
    # Log duplicate blocking for telemetry
    if duplicate_blocked:
        for value, info in duplicate_blocked.items():
            logger.info(f"[FACTS-PERSIST] Duplicate blocked: '{value}' already exists at rank {info.get('existing_rank')} for topic={info.get('topic')}")
    
    return store_count, update_count, stored_fact_keys, message_uuid, ambiguous_topics, canonicalization_result, rank_assignment_source, duplicate_blocked

