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
    project_id: Optional[str] = None  # Project ID for checking existing ranks
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
        
        # Determine starting rank based on rank_ordered flag
        if candidate.rank_ordered:
            # Explicit ordering: use ranks 1, 2, 3... (may overwrite existing ranks)
            start_rank = 1
        else:
            # Unranked/FIFO append: find max existing rank and append after it
            # Also check for legacy scalar/array facts and migrate them
            start_rank = 1  # Default if no existing facts
            if project_id:
                try:
                    from server.services.librarian import search_facts_ranked_list
                    from server.services.projects.project_resolver import validate_project_uuid
                    
                    # Validate project_id before querying
                    validate_project_uuid(project_id)
                    
                    # Check for ranked facts
                    # FIX: Use 10000 limit instead of 1000 for unbounded retrieval
                    existing_facts = search_facts_ranked_list(
                        project_id=project_id,
                        topic_key=canonical_topic,
                        limit=10000  # Get all facts to find max rank (unbounded, increased from 1000)
                    )
                    
                    # Now check max rank from ranked facts
                    if existing_facts:
                        max_rank = max(f.get("rank", 0) for f in existing_facts)
                        start_rank = max_rank + 1  # Append after max rank
                        logger.debug(f"[FACTS-PERSIST] Unranked write: appending after max_rank={max_rank}, starting at rank={start_rank}")
                except ValueError as e:
                    # Invalid project UUID - log and fallback
                    logger.warning(f"[FACTS-PERSIST] Invalid project_id for unranked append check: {e}")
                    start_rank = 1
                except Exception as e:
                    logger.warning(f"[FACTS-PERSIST] Failed to check existing ranks for unranked append: {e}", exc_info=True)
                    # Fallback to rank 1 if check fails
                    start_rank = 1
        
        # Create ranked_list_set operations
        for offset, value in enumerate(values):
            rank = start_rank + offset
            ops.append(FactsOp(
                op="ranked_list_set",
                list_key=list_key,
                rank=rank,
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
) -> Tuple[int, int, list, Optional[str], Optional[List[str]], Optional[Any]]:
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
        Tuple of (store_count, update_count, stored_fact_keys, message_uuid, ambiguous_topics, canonicalization_result):
        - store_count: Number of facts actually stored (new facts)
        - update_count: Number of facts actually updated (existing facts with changed values)
        - stored_fact_keys: List of fact keys that were stored/updated
        - message_uuid: The message_uuid used for fact storage (for exclusion in Facts-R)
        - ambiguous_topics: List of candidate topics if ranked list topic is ambiguous, None otherwise
        - canonicalization_result: CanonicalizationResult for telemetry (None if not available)
    """
    store_count = 0
    update_count = 0
    stored_fact_keys = []
    
    ambiguous_topics = None  # Will be set if ranked list topic resolution is ambiguous
    
    if not project_id:
        logger.warning(f"[FACTS-PERSIST] Skipping fact persistence: project_id is missing")
        return store_count, update_count, stored_fact_keys, None, None, None
    
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
            return store_count, update_count, stored_fact_keys, None, None, None
        
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
            return store_count, update_count, stored_fact_keys, None, None, None
    
    # Only extract facts from user messages
    if role != "user":
        logger.debug(f"[FACTS-PERSIST] Skipping fact extraction for role={role} (only user messages)")
        return store_count, update_count, stored_fact_keys, message_uuid, None, None
    
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
                project_id=project_id  # Pass project_id for checking existing max rank
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
            llm_response = None
            try:
                logger.debug(f"[FACTS-PERSIST] Calling Facts LLM (GPT-5 Nano) for message (message_uuid={message_uuid})")
                llm_response = await run_facts_llm(prompt)
            except FactsLLMTimeoutError as e:
                # Timeout error
                logger.error(f"[FACTS-PERSIST] ❌ Facts LLM (GPT-5 Nano) timed out: {e}")
                return -1, -1, [], message_uuid, None, None  # Negative counts indicate error
            except FactsLLMUnavailableError as e:
                # Unavailable error
                logger.error(f"[FACTS-PERSIST] ❌ Facts LLM (GPT-5 Nano) unavailable: {e}")
                return -1, -1, [], message_uuid, None, None  # Negative counts indicate error
            except FactsLLMInvalidJSONError as e:
                # Invalid JSON error
                logger.error(f"[FACTS-PERSIST] ❌ Facts LLM returned invalid JSON: {e}")
                return -1, -1, [], message_uuid, None, None  # Negative counts indicate error
            except FactsLLMError as e:
                # Other Facts LLM errors
                logger.error(f"[FACTS-PERSIST] ❌ Facts LLM failed: {e}")
                return -1, -1, [], message_uuid, None, None  # Negative counts indicate error
            
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
                
                # POST-PROCESS: Detect unranked writes and append after max rank
                # If Facts LLM extracted rank=1 but user didn't explicitly specify a rank,
                # and rank 1 already exists, append after max rank instead
                if ops_response and ops_response.ops:
                    import re
                    # Check if user message explicitly mentions a rank (#1, first, 1st, etc.)
                    explicit_rank_pattern = re.compile(r'\b(#1|first|1st|rank\s*1|number\s*1)\b', re.IGNORECASE)
                    has_explicit_rank = bool(explicit_rank_pattern.search(message_content))
                    
                    for op in ops_response.ops:
                        if op.op == "ranked_list_set" and op.rank == 1 and op.list_key and not has_explicit_rank:
                            # Check if rank 1 already exists for this topic
                            try:
                                from server.services.facts_normalize import extract_topic_from_list_key
                                topic = extract_topic_from_list_key(op.list_key)
                                if topic:
                                    from server.services.librarian import search_facts_ranked_list
                                    existing_facts = search_facts_ranked_list(
                                        project_id=project_id,
                                        topic_key=topic,
                                        limit=10000  # Get all to find max rank (increased from 1000)
                                    )
                                    if existing_facts:
                                        # Check if rank 1 exists
                                        has_rank_1 = any(f.get("rank") == 1 for f in existing_facts)
                                        if has_rank_1:
                                            # This is an unranked write - append after max rank
                                            max_rank = max(f.get("rank", 0) for f in existing_facts)
                                            op.rank = max_rank + 1
                                            logger.info(
                                                f"[FACTS-PERSIST] Detected unranked write: appending after max_rank={max_rank}, "
                                                f"new rank={op.rank} for topic={topic}"
                                            )
                            except Exception as e:
                                logger.warning(f"[FACTS-PERSIST] Failed to check existing ranks for unranked append: {e}")
                                # Continue with rank=1 if check fails
                
            except json.JSONDecodeError as e:
                logger.error(f"[FACTS-PERSIST] ❌ Failed to parse Facts LLM JSON response: {e}")
                logger.error(f"[FACTS-PERSIST] Raw response: {llm_response[:500] if llm_response else 'N/A'}")
                # Hard fail - return error indicator
                return -1, -1, [], message_uuid, None, None
            except Exception as e:
                logger.error(f"[FACTS-PERSIST] ❌ Failed to validate FactsOpsResponse: {e}")
                logger.error(f"[FACTS-PERSIST] Parsed data: {ops_data if 'ops_data' in locals() else 'N/A'}")
                # Hard fail - return error indicator
                return -1, -1, [], message_uuid, None, None
            
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
            return -1, -1, [], message_uuid, None, None
    
    # Check for clarification needed (applies to both routing candidate and LLM paths)
    if ops_response and ops_response.needs_clarification:
        ambiguous_topics = ops_response.needs_clarification
        logger.info(f"[FACTS-PERSIST] Clarification needed: {ambiguous_topics}")
        
        # Store raw response for diagnostics if write-intent
        if write_intent_detected and message_uuid:
            _raw_llm_responses[message_uuid] = {
                "prompt": prompt if 'prompt' in locals() else None,
                "raw_response": llm_response if 'llm_response' in locals() else None,
                "parsed_json": ops_data if 'ops_data' in locals() else None,
                "needs_clarification": ambiguous_topics,
                "ops_count": 0,
                "project_id": project_id,
                "chat_id": chat_id,
                "message_id": message_id
            }
        
        return store_count, update_count, stored_fact_keys, message_uuid, ambiguous_topics, canonicalization_result
    
    # Validate ops_response exists before applying
    if not ops_response:
        logger.error(f"[FACTS-PERSIST] ❌ No ops_response available after conversion/LLM extraction")
        return -1, -1, [], message_uuid, None, None
    
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
            "prompt": prompt if 'prompt' in locals() else None,
            "raw_llm_response": llm_response if 'llm_response' in locals() else None,
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
        logger.error(f"[FACTS-PERSIST] Raw LLM response (first 500 chars): {llm_response[:500] if llm_response and 'llm_response' in locals() else 'N/A'}")
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
    
    return store_count, update_count, stored_fact_keys, message_uuid, ambiguous_topics, canonicalization_result

