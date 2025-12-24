"""
Synchronous Facts persistence module.

This module provides a direct, synchronous path for storing facts that does NOT
depend on the Memory Service indexing pipeline. Facts are stored immediately
and deterministically, ensuring Facts-S/U counts are always truthful.
"""
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


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
    source_id: Optional[str] = None
) -> Tuple[int, int, list]:
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
        Tuple of (store_count, update_count, stored_fact_keys, message_uuid):
        - store_count: Number of facts actually stored (new facts)
        - update_count: Number of facts actually updated (existing facts with changed values)
        - stored_fact_keys: List of fact keys that were stored/updated
        - message_uuid: The message_uuid used for fact storage (for exclusion in Facts-R)
    """
    store_count = 0
    update_count = 0
    stored_fact_keys = []
    
    if not project_id:
        logger.warning(f"[FACTS-PERSIST] Skipping fact persistence: project_id is missing")
        return store_count, update_count, stored_fact_keys, None
    
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
    
    # Only extract facts from user messages (for now)
    if role != "user":
        logger.debug(f"[FACTS-PERSIST] Skipping fact extraction for role={role} (only user messages)")
        return store_count, update_count, stored_fact_keys, message_uuid
    
    try:
        # Import here to avoid circular dependencies
        from memory_service.fact_extractor import get_fact_extractor
        from memory_service.memory_dashboard import db
        
        # Extract facts
        extractor = get_fact_extractor()
        extracted_facts = extractor.extract_facts(message_content, role=role)
        
        if not extracted_facts:
            logger.debug(f"[FACTS-PERSIST] No facts extracted from message (message_uuid={message_uuid})")
            return store_count, update_count, stored_fact_keys, message_uuid
        
        logger.info(f"[FACTS-PERSIST] Extracted {len(extracted_facts)} facts from message (message_uuid={message_uuid})")
        
        # Store each fact synchronously
        for idx, fact in enumerate(extracted_facts, 1):
            fact_key = fact.get("fact_key")
            value_text = fact.get("value_text")
            value_type = fact.get("value_type", "string")
            confidence = fact.get("confidence", 1.0)
            
            if not fact_key:
                logger.warning(f"[FACTS-PERSIST] Fact {idx}/{len(extracted_facts)} missing fact_key, skipping")
                continue
            
            try:
                # Store fact directly (synchronous DB write)
                fact_id, action_type = db.store_project_fact(
                    project_id=project_id,
                    fact_key=fact_key,
                    value_text=value_text,
                    value_type=value_type,
                    source_message_uuid=message_uuid,
                    confidence=confidence,
                    source_id=source_id
                )
                
                # Count based on actual DB write result
                if action_type == "store":
                    store_count += 1
                    logger.debug(f"[FACTS-PERSIST] ✅ STORE fact {idx}/{len(extracted_facts)}: {fact_key} = {value_text} (fact_id={fact_id})")
                elif action_type == "update":
                    update_count += 1
                    logger.debug(f"[FACTS-PERSIST] ✅ UPDATE fact {idx}/{len(extracted_facts)}: {fact_key} = {value_text} (fact_id={fact_id})")
                
                stored_fact_keys.append(fact_key)
                
            except Exception as e:
                logger.error(f"[FACTS-PERSIST] ❌ Failed to store fact {fact_key}: {e}", exc_info=True)
                # Continue with other facts even if one fails
        
        logger.info(
            f"[FACTS-PERSIST] ✅ Persisted facts: S={store_count} U={update_count} "
            f"keys={stored_fact_keys} (message_uuid={message_uuid})"
        )
        
    except Exception as e:
        logger.error(f"[FACTS-PERSIST] ❌ Exception during fact persistence: {e}", exc_info=True)
    
    return store_count, update_count, stored_fact_keys, message_uuid

