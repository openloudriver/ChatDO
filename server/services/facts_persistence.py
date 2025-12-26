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
import re
from typing import Dict, Optional, Tuple, List
from datetime import datetime

logger = logging.getLogger(__name__)


def resolve_ranked_list_topic(
    message_content: str,
    retrieved_facts: Optional[List[Dict]] = None,
    project_id: Optional[str] = None,
    candidate: Optional[Dict] = None
) -> Tuple[Optional[str], Optional[List[str]]]:
    """
    Resolve topic for ranked list mutations using strict inference order.
    
    Order:
    1. Explicit topic in user message ("My favorite cryptos are...") OR candidate.explicit_topic
    2. Schema-hint anchoring (from retrieved facts with schema_hint.domain == "ranked_list")
    3. DB-backed recency fallback (get_recent_ranked_list_keys) - most recently updated list
    4. Optional small keyword map (only for obvious nouns like colors/candies)
    
    Args:
        message_content: User message content
        retrieved_facts: Optional list of retrieved facts (from current conversation context)
        project_id: Optional project ID for DB recency lookup
        candidate: Optional ranked-list candidate with explicit_topic field
        
    Returns:
        Tuple of (resolved_topic, ambiguous_candidates):
        - resolved_topic: Resolved topic (e.g., "crypto", "colors") or None if ambiguous/unresolvable
        - ambiguous_candidates: List of candidate topics if ambiguous, None if resolved or unresolvable
    """
    from memory_service.fact_extractor import get_fact_extractor
    from server.services.librarian import get_recent_ranked_list_keys
    
    extractor = get_fact_extractor()
    message_lower = message_content.lower()
    
    # 1. Explicit topic in user message OR candidate.explicit_topic
    if candidate and candidate.get("explicit_topic"):
        explicit_topic = candidate.get("explicit_topic")
        logger.debug(f"[TOPIC-RESOLVE] Found explicit topic in candidate: {explicit_topic}")
        return explicit_topic, None
    
    # Look for "favorite X" pattern in message (but not "favorite is X")
    # Only extract if it's not a verb
    match = extractor._extract_topic_from_context(message_content, len(message_content))
    if match:
        # Double-check: don't use verbs as topics
        verbs = {'is', 'are', 'was', 'were', 'be', 'been', 'being'}
        if match.lower() not in verbs:
            logger.debug(f"[TOPIC-RESOLVE] Found explicit topic in message: {match}")
            return match, None
    
    # 2. Schema-hint anchoring (preferred for follow-ups)
    if retrieved_facts:
        schema_hints = []
        for fact in retrieved_facts:
            metadata = fact.get("metadata", {}) if isinstance(fact, dict) else getattr(fact, "metadata", {})
            schema_hint = metadata.get("schema_hint") if isinstance(metadata, dict) else None
            if schema_hint and schema_hint.get("domain") == "ranked_list":
                key = schema_hint.get("key", "")
                # Extract base key: user.favorites.<topic> from user.favorites.<topic>.<rank>
                import re
                base_match = re.match(r'^user\.favorites\.([^.]+)', key)
                if base_match:
                    topic = base_match.group(1)
                    schema_hints.append(topic)
        
        if schema_hints:
            distinct_topics = list(set(schema_hints))
            if len(distinct_topics) == 1:
                logger.debug(f"[TOPIC-RESOLVE] Resolved via schema hint: {distinct_topics[0]}")
                return distinct_topics[0], None
            elif len(distinct_topics) > 1:
                logger.warning(f"[TOPIC-RESOLVE] Ambiguous schema hints: {distinct_topics} - user must choose")
                return None, distinct_topics  # Ambiguous - return candidates
    
    # 3. DB-backed recency fallback
    if project_id:
        try:
            # project_id must be UUID (validated in persist_facts_synchronously)
            recent_keys = get_recent_ranked_list_keys(project_id, limit=5)
            if recent_keys:
                # Extract topics from keys: user.favorites.<topic>
                import re
                topics = []
                for key in recent_keys:
                    match = re.match(r'^user\.favorites\.([^.]+)', key)
                    if match:
                        topics.append(match.group(1))
                
                distinct_topics = list(set(topics))
                if len(distinct_topics) == 1:
                    logger.debug(f"[TOPIC-RESOLVE] Resolved via DB recency: {distinct_topics[0]}")
                    return distinct_topics[0], None
                elif len(distinct_topics) > 1:
                    logger.warning(f"[TOPIC-RESOLVE] Ambiguous recent topics: {distinct_topics} - user must choose")
                    return None, distinct_topics  # Ambiguous - return candidates
        except Exception as e:
            logger.debug(f"[TOPIC-RESOLVE] DB recency lookup failed: {e}")
    
    # 4. Optional small keyword map (only for obvious nouns)
    topic_keywords = {
        'crypto': 'crypto', 'cryptos': 'crypto', 'cryptocurrency': 'crypto', 'cryptocurrencies': 'crypto',
        'color': 'colors', 'colors': 'colors',
        'candy': 'candies', 'candies': 'candies',
        'pie': 'pies', 'pies': 'pies',
        'tv': 'tv', 'show': 'tv', 'television': 'tv',
        'food': 'food', 'textile': 'textiles', 'textiles': 'textiles'
    }
    for keyword, topic in topic_keywords.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', message_lower):
            logger.debug(f"[TOPIC-RESOLVE] Resolved via keyword map: {topic}")
            return topic, None
    
    logger.debug("[TOPIC-RESOLVE] No topic resolved - requires explicit topic or schema hint")
    return None, None


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


def persist_facts_synchronously(
    project_id: str,
    message_content: str,
    role: str,
    message_uuid: Optional[str] = None,
    chat_id: Optional[str] = None,
    message_id: Optional[str] = None,
    timestamp: Optional[datetime] = None,
    message_index: Optional[int] = None,
    source_id: Optional[str] = None,
    retrieved_facts: Optional[List[Dict]] = None  # For schema-hint topic resolution
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
            return store_count, update_count, stored_fact_keys, None
        
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
            return store_count, update_count, stored_fact_keys, None
    
    # Only extract facts from user messages
    if role != "user":
        logger.debug(f"[FACTS-PERSIST] Skipping fact extraction for role={role} (only user messages)")
        return store_count, update_count, stored_fact_keys, message_uuid, None
    
    # NEW ARCHITECTURE: Use Qwen LLM to produce JSON operations
    try:
        from server.services.facts_llm.client import run_facts_llm, FactsLLMError
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
        
        # Call Qwen LLM (hard fail if unavailable)
        try:
            logger.debug(f"[FACTS-PERSIST] Calling Facts LLM for message (message_uuid={message_uuid})")
            llm_response = run_facts_llm(prompt)
        except FactsLLMError as e:
            # Hard fail - return error indicator
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
            logger.error(f"[FACTS-PERSIST] Raw response: {llm_response[:500]}")
            # Hard fail - return error indicator
            return -1, -1, [], message_uuid, None
        except Exception as e:
            logger.error(f"[FACTS-PERSIST] ❌ Failed to validate FactsOpsResponse: {e}")
            logger.error(f"[FACTS-PERSIST] Parsed data: {ops_data if 'ops_data' in locals() else 'N/A'}")
            # Hard fail - return error indicator
            return -1, -1, [], message_uuid, None
        
        # Check for clarification needed
        if ops_response.needs_clarification:
            ambiguous_topics = ops_response.needs_clarification
            logger.info(f"[FACTS-PERSIST] Clarification needed: {ambiguous_topics}")
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

