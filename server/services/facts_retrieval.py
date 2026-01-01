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
    rank_applied: bool = False  # Whether rank filtering was applied
    rank_result_found: Optional[bool] = None  # Whether rank filter found results (None if rank not applied)
    ordinal_parse_source: str = "none"  # Source of ordinal detection: "router" | "planner" | "none"
    max_available_rank: Optional[int] = None  # Maximum rank available for this topic (for bounds checking)
    
    def __post_init__(self):
        """Initialize defaults for optional fields."""
        if self.canonical_keys is None:
            self.canonical_keys = []


def execute_facts_plan(
    project_uuid: str,
    plan: FactsQueryPlan,
    exclude_message_uuid: Optional[str] = None,
    ordinal_parse_source: str = "none"  # Source of ordinal detection: "router" | "planner" | "none"
) -> FactsAnswer:
    """
    Execute a Facts query plan deterministically.
    
    This function performs direct DB queries - no LLM calls.
    
    Args:
        project_uuid: Project UUID (must be valid UUID)
        plan: FactsQueryPlan to execute
        exclude_message_uuid: Optional message UUID to exclude from results
        ordinal_parse_source: Source of ordinal detection ("router" | "planner" | "none")
        
    Returns:
        FactsAnswer with facts, count, canonical keys, and telemetry fields
        
    Raises:
        ValueError: If project_uuid is not a valid UUID
    """
    # Validate project UUID
    validate_project_uuid(project_uuid)
    
    facts = []
    canonical_keys = set()
    rank_applied = False
    rank_result_found = None
    max_available_rank = None
    
    try:
        if plan.intent == "facts_get_ranked_list":
            # Query ranked list directly from DB
            # Extract topic from list_key if not provided, or build list_key from topic
            # Ensure topic is canonicalized using Canonicalizer subsystem (defensive check)
            # DEDUPLICATION: Cache canonicalization result per request
            from server.services.canonicalizer import canonicalize_topic as canonicalize_with_subsystem
            canonicalization_cache = {}  # Cache per request to avoid duplicate calls
            
            if not plan.topic and plan.list_key:
                # Extract topic from list_key (e.g., "user.favorites.crypto" -> "crypto")
                from server.services.facts_normalize import extract_topic_from_list_key
                raw_topic = extract_topic_from_list_key(plan.list_key)
                if raw_topic:
                    # Use cache if available
                    if raw_topic not in canonicalization_cache:
                        canonicalization_result = canonicalize_with_subsystem(raw_topic, invoke_teacher=False)
                        canonicalization_cache[raw_topic] = canonicalization_result
                    plan.topic = canonicalization_cache[raw_topic].canonical_topic
            
            if not plan.list_key and plan.topic:
                # Canonicalize topic and build list_key
                if plan.topic not in canonicalization_cache:
                    canonicalization_result = canonicalize_with_subsystem(plan.topic, invoke_teacher=False)
                    canonicalization_cache[plan.topic] = canonicalization_result
                plan.topic = canonicalization_cache[plan.topic].canonical_topic
                plan.list_key = canonical_list_key(plan.topic)
            elif plan.topic:
                # Ensure topic is canonicalized (defensive - should already be canonical)
                if plan.topic not in canonicalization_cache:
                    canonicalization_result = canonicalize_with_subsystem(plan.topic, invoke_teacher=False)
                    canonicalization_cache[plan.topic] = canonicalization_result
                plan.topic = canonicalization_cache[plan.topic].canonical_topic
            
            if plan.list_key and plan.topic:
                try:
                    # STORAGE IS UNBOUNDED: Facts are stored without limits.
                    # RETRIEVAL IS PAGINATED: List queries use plan.limit for pagination (default 100, max 1000).
                    # ORDINAL QUERIES USE UNBOUNDED RETRIEVAL: When plan.rank is set, we retrieve all facts
                    # internally (limit=None) to find the specific rank, then filter to return only that rank.
                    # This ensures ordinal queries work correctly even with >1000 facts.
                    retrieval_limit = None if plan.rank is not None else plan.limit  # None = unbounded retrieval
                    ranked_facts = search_facts_ranked_list(
                        project_id=project_uuid,
                        topic_key=plan.topic,
                        limit=retrieval_limit,  # None for ordinal queries (unbounded)
                        exclude_message_uuid=exclude_message_uuid
                    )
                except Exception as e:
                    logger.error(f"[FACTS-RETRIEVAL] Failed to search ranked list: {e}", exc_info=True)
                    ranked_facts = []
                
                # Calculate max_available_rank for bounds checking
                if ranked_facts:
                    max_available_rank = max(f.get("rank", 0) for f in ranked_facts)
                
                # DEFENSIVE DEDUPLICATION: Remove duplicates by normalized value (safety net)
                # This prevents duplicates from appearing in retrieval even if they somehow exist in DB
                # Keep the earliest occurrence (lowest rank) for each normalized value
                from server.services.facts_apply import normalize_rank_item
                seen_normalized = {}  # normalized_value -> fact (keep first occurrence)
                deduplicated_facts = []
                for fact in ranked_facts:
                    normalized_value = normalize_rank_item(fact.get("value_text", ""))
                    if normalized_value not in seen_normalized:
                        seen_normalized[normalized_value] = fact
                        deduplicated_facts.append(fact)
                    else:
                        # Duplicate found - log warning but keep first occurrence
                        existing_rank = seen_normalized[normalized_value].get("rank")
                        duplicate_rank = fact.get("rank")
                        logger.warning(
                            f"[FACTS-RETRIEVAL] Duplicate detected in retrieval: "
                            f"value='{fact.get('value_text')}' (normalized: '{normalized_value}') "
                            f"at ranks {existing_rank} and {duplicate_rank}. "
                            f"Keeping rank {existing_rank} (earliest occurrence)."
                        )
                
                if len(deduplicated_facts) < len(ranked_facts):
                    logger.info(
                        f"[FACTS-RETRIEVAL] Deduplication removed {len(ranked_facts) - len(deduplicated_facts)} "
                        f"duplicate(s) from ranked list for topic={plan.topic}"
                    )
                    ranked_facts = deduplicated_facts
                
                # Convert to answer format
                # If rank is specified (ordinal query), filter to only that rank FIRST
                rank_applied = plan.rank is not None
                for fact in ranked_facts:
                    fact_rank = fact.get("rank")
                    # If plan.rank is set, only include facts matching that rank
                    if plan.rank is not None:
                        if fact_rank != plan.rank:
                            continue
                        rank_result_found = True  # Found at least one fact at requested rank
                    
                    facts.append({
                        "fact_key": fact.get("fact_key", ""),
                        "value_text": fact.get("value_text", ""),
                        "rank": fact_rank,
                        "source_message_uuid": fact.get("source_message_uuid"),
                        "created_at": fact.get("created_at")
                    })
                    # Extract canonical key (user.favorites.<topic>)
                    fact_key = fact.get("fact_key", "")
                    if "." in fact_key:
                        parts = fact_key.rsplit(".", 1)  # Split on last dot
                        if parts[0].startswith("user.favorites."):
                            canonical_keys.add(parts[0])
                
                # Set rank_result_found to False if rank was applied but no facts found
                if rank_applied and rank_result_found is None:
                    rank_result_found = False
                
                if plan.rank is not None:
                    logger.info(
                        f"[FACTS-RETRIEVAL] Retrieved {len(facts)} ranked list facts for {plan.list_key} at rank {plan.rank} "
                        f"(rank_applied={rank_applied}, rank_result_found={rank_result_found}, "
                        f"max_available_rank={max_available_rank}, ordinal_parse_source={ordinal_parse_source})"
                    )
                else:
                    logger.debug(f"[FACTS-RETRIEVAL] Retrieved {len(facts)} ranked list facts for {plan.list_key} (max_available_rank={max_available_rank})")
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
        canonical_keys=list(canonical_keys),
        rank_applied=rank_applied,
        rank_result_found=rank_result_found,
        ordinal_parse_source=ordinal_parse_source,
        max_available_rank=max_available_rank
    )

