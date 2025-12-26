"""
Deterministic Facts Retrieval Executor.

Executes FactsQueryPlan deterministically (no LLM calls).
"""
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass

from server.contracts.facts_ops import FactsQueryPlan
from server.services.projects.project_resolver import validate_project_uuid
from server.services.facts_normalize import canonical_list_key
from memory_service.memory_dashboard import db
from server.services.librarian import search_facts_ranked_list

logger = logging.getLogger(__name__)


@dataclass
class FactsAnswer:
    """Result of executing a facts query plan."""
    facts: List[Dict]
    count: int  # Number of facts returned
    canonical_keys: List[str]  # Distinct canonical keys (for Facts-R counting)


def execute_facts_plan(
    project_uuid: str,
    plan: FactsQueryPlan,
    exclude_message_uuid: Optional[str] = None
) -> FactsAnswer:
    """
    Execute a Facts query plan deterministically.
    
    This function performs direct DB queries - no LLM calls.
    
    Args:
        project_uuid: Project UUID (must be valid UUID)
        plan: FactsQueryPlan to execute
        exclude_message_uuid: Optional message UUID to exclude from results
        
    Returns:
        FactsAnswer with facts, count, and canonical keys
        
    Raises:
        ValueError: If project_uuid is not a valid UUID
    """
    # Validate project UUID
    validate_project_uuid(project_uuid)
    
    facts = []
    canonical_keys = set()
    
    try:
        if plan.intent == "facts_get_ranked_list":
            # Query ranked list directly from DB
            # Extract topic from list_key if not provided, or build list_key from topic
            # Ensure topic is canonicalized (defensive check)
            from server.services.facts_topic import canonicalize_topic
            
            if not plan.topic and plan.list_key:
                # Extract topic from list_key (e.g., "user.favorites.crypto" -> "crypto")
                from server.services.facts_normalize import extract_topic_from_list_key
                raw_topic = extract_topic_from_list_key(plan.list_key)
                if raw_topic:
                    plan.topic = canonicalize_topic(raw_topic)
            
            if not plan.list_key and plan.topic:
                # Canonicalize topic and build list_key
                plan.topic = canonicalize_topic(plan.topic)
                plan.list_key = canonical_list_key(plan.topic)
            elif plan.topic:
                # Ensure topic is canonicalized
                plan.topic = canonicalize_topic(plan.topic)
            
            if plan.list_key and plan.topic:
                try:
                    # Use canonicalized topic for retrieval
                    ranked_facts = search_facts_ranked_list(
                        project_id=project_uuid,
                        topic_key=plan.topic,
                        limit=plan.limit,
                        exclude_message_uuid=exclude_message_uuid
                    )
                except Exception as e:
                    logger.error(f"[FACTS-RETRIEVAL] Failed to search ranked list: {e}", exc_info=True)
                    ranked_facts = []
                
                # Convert to answer format
                for fact in ranked_facts:
                    facts.append({
                        "fact_key": fact.get("fact_key", ""),
                        "value_text": fact.get("value_text", ""),
                        "rank": fact.get("rank"),
                        "source_message_uuid": fact.get("source_message_uuid"),
                        "created_at": fact.get("created_at")
                    })
                    # Extract canonical key (user.favorites.<topic>)
                    fact_key = fact.get("fact_key", "")
                    if "." in fact_key:
                        parts = fact_key.rsplit(".", 1)  # Split on last dot
                        if parts[0].startswith("user.favorites."):
                            canonical_keys.add(parts[0])
                
                logger.debug(f"[FACTS-RETRIEVAL] Retrieved {len(facts)} ranked list facts for {plan.list_key}")
            else:
                logger.warning(f"[FACTS-RETRIEVAL] Missing list_key or topic for ranked list query: list_key={plan.list_key}, topic={plan.topic}")
        
        elif plan.intent == "facts_get_by_prefix":
            # Query facts by key prefix
            if plan.key_prefix:
                source_id = f"project-{project_uuid}"
                try:
                    db_facts = db.search_current_facts(
                        project_id=project_uuid,
                        query=plan.key_prefix,  # Use prefix as query
                        limit=plan.limit,
                        source_id=source_id,
                        exclude_message_uuid=exclude_message_uuid
                    )
                except Exception as e:
                    logger.error(f"[FACTS-RETRIEVAL] Failed to search facts by prefix: {e}", exc_info=True)
                    db_facts = []
                
                # Filter to only facts matching the prefix
                for fact in db_facts:
                    fact_key = fact.get("fact_key", "")
                    if fact_key.startswith(plan.key_prefix):
                        facts.append({
                            "fact_key": fact_key,
                            "value_text": fact.get("value_text", ""),
                            "source_message_uuid": fact.get("source_message_uuid"),
                            "created_at": fact.get("created_at")
                        })
                        # Extract canonical prefix for counting
                        if "." in fact_key:
                            parts = fact_key.rsplit(".", 1)
                            canonical_keys.add(parts[0])
                
                logger.debug(f"[FACTS-RETRIEVAL] Retrieved {len(facts)} facts for prefix {plan.key_prefix}")
        
        elif plan.intent == "facts_get_exact_key":
            # Query exact fact key
            if plan.fact_key:
                source_id = f"project-{project_uuid}"
                try:
                    current_fact = db.get_current_fact(
                        project_id=project_uuid,
                        fact_key=plan.fact_key,
                        source_id=source_id
                    )
                except Exception as e:
                    logger.error(f"[FACTS-RETRIEVAL] Failed to get exact fact: {e}", exc_info=True)
                    current_fact = None
                
                if current_fact:
                    # Check if we should exclude this fact
                    if exclude_message_uuid and current_fact.get("source_message_uuid") == exclude_message_uuid:
                        logger.debug(f"[FACTS-RETRIEVAL] Excluded fact from current message: {plan.fact_key}")
                    else:
                        facts.append({
                            "fact_key": current_fact.get("fact_key", ""),
                            "value_text": current_fact.get("value_text", ""),
                            "source_message_uuid": current_fact.get("source_message_uuid"),
                            "created_at": current_fact.get("created_at")
                        })
                        canonical_keys.add(plan.fact_key)
                
                logger.debug(f"[FACTS-RETRIEVAL] Retrieved {len(facts)} facts for exact key {plan.fact_key}")
    
    except Exception as e:
        # Catch any unexpected errors in the plan execution
        logger.error(f"[FACTS-RETRIEVAL] Unexpected error executing facts plan: {e}", exc_info=True)
        # Return empty answer (graceful degradation for retrieval)
    
    return FactsAnswer(
        facts=facts,
        count=len(facts),
        canonical_keys=list(canonical_keys)
    )

