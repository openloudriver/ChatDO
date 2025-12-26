"""
Synchronous Facts persistence module.

This module provides a direct, synchronous path for storing facts that does NOT
depend on the Memory Service indexing pipeline. Facts are stored immediately
and deterministically, ensuring Facts-S/U counts are always truthful.

Facts DB contract: project_facts.project_id must always be the project UUID string.
Never use project name/slug for DB access.

NEW ARCHITECTURE: Uses Qwen LLM to produce JSON operations, then applies them deterministically.
No regex/spaCy extraction - single path only.
"""
import logging
import json
from typing import Dict, Optional, Tuple, List, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# In-memory store for raw LLM responses (keyed by message_uuid) for quick inspection
_raw_llm_responses: Dict[str, Dict[str, Any]] = {}


# REMOVED: resolve_ranked_list_topic() - Legacy function no longer used
# Topic resolution for ranked lists is now handled by Qwen LLM in the Facts extraction prompt
# This ensures all Facts behavior goes through the unified Qwen → JSON ops → deterministic apply path


def get_or_create_message_uuid(
    project_id: str,
    chat_id: str,
    message_id: str,
    role: str,
    content: str,
    timestamp: datetime,
    message_index: int
) -> Optional[str]:
    """
    Get or create message_uuid for a message.
    
    This ensures we have a message_uuid before storing facts, even if
    the Memory Service is unavailable.
    
    Args:
        project_id: Project ID
        chat_id: Chat ID
        message_id: Message ID
        role: Message role
        content: Message content
        timestamp: Message timestamp
        message_index: Message index in conversation
        
    Returns:
        message_uuid if successful, None otherwise
    """
    try:
        from memory_service.memory_dashboard import db
        
        source_id = f"project-{project_id}"
        db.init_db(source_id, project_id=project_id)
        
        # Upsert source (chat messages don't have a root_path)
        db.upsert_source(source_id, project_id, "", None, None)
        
        # Upsert chat message (generates message_uuid if not exists)
        chat_message_id = db.upsert_chat_message(
            source_id=source_id,
            project_id=project_id,
            chat_id=chat_id,
            message_id=message_id,
            role=role,
            content=content,
            timestamp=timestamp,
            message_index=message_index
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
    write_intent_detected: bool = False  # Flag to enable enhanced diagnostics
) -> Tuple[int, int, list, Optional[str], Optional[List[str]]]:
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
        Tuple of (store_count, update_count, stored_fact_keys, message_uuid, ambiguous_topics):
        - store_count: Number of facts actually stored (new facts)
        - update_count: Number of facts actually updated (existing facts with changed values)
        - stored_fact_keys: List of fact keys that were stored/updated
        - message_uuid: The message_uuid used for fact storage (for exclusion in Facts-R)
        - ambiguous_topics: List of candidate topics if ranked list topic is ambiguous, None otherwise
    """
    store_count = 0
    update_count = 0
    stored_fact_keys = []
    
    ambiguous_topics = None  # Will be set if ranked list topic resolution is ambiguous
    
    if not project_id:
        logger.warning(f"[FACTS-PERSIST] Skipping fact persistence: project_id is missing")
        return store_count, update_count, stored_fact_keys, None, None
    
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
            return store_count, update_count, stored_fact_keys, None, None
        
        message_uuid = get_or_create_message_uuid(
            project_id=project_id,
            chat_id=chat_id,
            message_id=message_id,
            role=role,
            content=message_content,
            timestamp=timestamp,
            message_index=message_index
        )
        
        if not message_uuid:
            logger.warning(f"[FACTS-PERSIST] Failed to get/create message_uuid, skipping fact persistence")
            return store_count, update_count, stored_fact_keys, None, None
    
    # Only extract facts from user messages
    if role != "user":
        logger.debug(f"[FACTS-PERSIST] Skipping fact extraction for role={role} (only user messages)")
        return store_count, update_count, stored_fact_keys, message_uuid, None
    
    # NEW ARCHITECTURE: Use Qwen LLM to produce JSON operations
    try:
        from server.services.facts_llm.client import (
            run_facts_llm,
            FactsLLMError,
            FactsLLMTimeoutError,
            FactsLLMUnavailableError,
            FactsLLMInvalidJSONError,
            FACTS_LLM_TIMEOUT_S
        )
        from server.services.facts_llm.prompts import build_facts_extraction_prompt
        from server.contracts.facts_ops import FactsOpsResponse
        from server.services.facts_apply import apply_facts_ops
        
        # Build prompt for Qwen
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
        
        # Call Qwen LLM (hard fail if unavailable, with retry and better error classification)
        llm_response = None
        ops_response = None
        try:
            logger.debug(f"[FACTS-PERSIST] Calling Facts LLM for message (message_uuid={message_uuid}, timeout={FACTS_LLM_TIMEOUT_S}s)")
            llm_response = await run_facts_llm(prompt, max_retries=1)
        except FactsLLMTimeoutError as e:
            # Timeout error - include timeout value in log
            logger.error(
                f"[FACTS-PERSIST] ❌ Facts LLM timed out after {FACTS_LLM_TIMEOUT_S}s (with retry): {e}"
            )
            # Return special error indicator with timeout classification
            return -1, -1, [], message_uuid, None  # Negative counts indicate error
        except FactsLLMUnavailableError as e:
            # Unavailable error - Ollama not reachable
            logger.error(f"[FACTS-PERSIST] ❌ Facts LLM (Ollama) unavailable: {e}")
            # Return special error indicator with unavailable classification
            return -1, -1, [], message_uuid, None  # Negative counts indicate error
        except FactsLLMInvalidJSONError as e:
            # Invalid JSON error - no retry
            logger.error(f"[FACTS-PERSIST] ❌ Facts LLM returned invalid JSON: {e}")
            # Return special error indicator with invalid JSON classification
            return -1, -1, [], message_uuid, None  # Negative counts indicate error
        except FactsLLMError as e:
            # Other Facts LLM errors
            logger.error(f"[FACTS-PERSIST] ❌ Facts LLM failed: {e}")
            # Return special error indicator (will be handled by caller)
            return -1, -1, [], message_uuid, None  # Negative counts indicate error
        
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
            
        except json.JSONDecodeError as e:
            logger.error(f"[FACTS-PERSIST] ❌ Failed to parse Facts LLM JSON response: {e}")
            logger.error(f"[FACTS-PERSIST] Raw response: {llm_response[:500] if llm_response else 'N/A'}")
            # Hard fail - return error indicator
            return -1, -1, [], message_uuid, None
        except Exception as e:
            logger.error(f"[FACTS-PERSIST] ❌ Failed to validate FactsOpsResponse: {e}")
            logger.error(f"[FACTS-PERSIST] Parsed data: {ops_data if 'ops_data' in locals() else 'N/A'}")
            # Hard fail - return error indicator
            return -1, -1, [], message_uuid, None
        
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
                llm_response = await run_facts_llm(force_prompt, max_retries=1)
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
        
        # Check for clarification needed
        if ops_response.needs_clarification:
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
            
            return store_count, update_count, stored_fact_keys, message_uuid, ambiguous_topics
        
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
        
    except Exception as e:
        logger.error(f"[FACTS-PERSIST] ❌ Exception during fact persistence: {e}", exc_info=True)
        # Hard fail on unexpected exceptions
        return -1, -1, [], message_uuid, None
    
    return store_count, update_count, stored_fact_keys, message_uuid, ambiguous_topics

