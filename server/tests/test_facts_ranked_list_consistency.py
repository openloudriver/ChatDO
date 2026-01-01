"""
Regression tests for ranked-list consistency: duplicates and rank directives.

Tests the exact bug: "Breakfast Burritos" appearing at multiple ranks and not respecting #2 directive.
"""
import pytest
from datetime import datetime, timezone
from server.services.facts_persistence import persist_facts_synchronously
from server.services.facts_apply import validate_ranked_list_invariants, _get_ranked_list_items, normalize_rank_item
from server.services.facts_normalize import canonical_ranked_topic_key
from server.services.librarian import search_facts_ranked_list
from memory_service.memory_dashboard import db


@pytest.mark.asyncio
async def test_breakfast_burritos_duplicate_prevention(test_db_setup, test_thread_id):
    """
    Regression Test: "#2 favorite" should insert at rank 2, not create duplicates.
    
    Bug: "My #2 favorite weekend breakfast is breakfast burritos" kept item at #5,
    then mysteriously moved to #1, then wasn't at #1 anymore.
    
    Scenario:
    - Seed list: [Pancakes, Omelets, French Toast, Bagels, Breakfast Burritos]
    - Issue write: "My #2 favorite weekend breakfast is breakfast burritos."
    - Assert resulting list:
      - Contains no duplicates by normalized form
      - "breakfast burritos" appears exactly once
      - "breakfast burritos" is at rank 2
      - List is: [Pancakes, Breakfast Burritos, Omelets, French Toast, Bagels]
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Step 1: Seed initial ranked list
    seed_message = "My favorite weekend breakfasts are Pancakes, Omelets, French Toast, Bagels, Breakfast Burritos."
    seed_result = await persist_facts_synchronously(
        project_id=project_id,
        message_content=seed_message,
        role="user",
        chat_id=test_thread_id,
        message_id=f"{test_thread_id}-user-1",
        timestamp=datetime.now(timezone.utc),
        message_index=0,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    assert seed_result.store_count == 5, f"Expected 5 items stored, got {seed_result.store_count}"
    
    # Verify initial state
    # CRITICAL: Use canonical_ranked_topic_key (single source of truth) for consistency
    # This ensures "weekend breakfasts" and "weekend breakfast" map to the same list_key
    from server.services.facts_normalize import canonical_ranked_topic_key
    list_key = canonical_ranked_topic_key("weekend breakfasts")
    conn = db.get_db_connection(source_id, project_id=project_id)
    initial_items = _get_ranked_list_items(conn, project_id, list_key)
    conn.close()
    initial_items.sort(key=lambda x: x["rank"])
    
    # Verify Breakfast Burritos is at rank 5 initially
    burritos_initial = next((item for item in initial_items if normalize_rank_item(item["value_text"]) == normalize_rank_item("Breakfast Burritos")), None)
    assert burritos_initial is not None, "Breakfast Burritos should exist in initial list"
    assert burritos_initial["rank"] == 5, f"Breakfast Burritos should be at rank 5 initially, got {burritos_initial['rank']}"
    
    # Step 2: Move Breakfast Burritos to rank 2 (using lowercase to test normalization)
    # CRITICAL: Use "weekend breakfast" (singular) to test that it resolves to the same list_key
    mutation_message = "My #2 favorite weekend breakfast is breakfast burritos."
    
    # Verify both phrasings resolve to the same canonical list key
    mutation_list_key = canonical_ranked_topic_key("weekend breakfast")  # Singular
    seed_list_key = canonical_ranked_topic_key("weekend breakfasts")  # Plural
    assert mutation_list_key == seed_list_key, \
        f"Topic canonicalization drift detected! " \
        f"'weekend breakfast' -> {mutation_list_key!r}, " \
        f"'weekend breakfasts' -> {seed_list_key!r}. " \
        f"They must resolve to the same list_key."
    assert mutation_list_key == list_key, \
        f"Mutation list_key {mutation_list_key!r} must match seed list_key {list_key!r}"
    
    mutation_result = await persist_facts_synchronously(
        project_id=project_id,
        message_content=mutation_message,
        role="user",
        chat_id=test_thread_id,
        message_id=f"{test_thread_id}-user-2",
        timestamp=datetime.now(timezone.utc),
        message_index=1,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    
    # Step 3: Verify mutation result
    assert mutation_result.update_count >= 1, "Should have at least 1 update (Breakfast Burritos moved)"
    
    # Step 4: Verify final list state (use the same list_key as seed)
    conn = db.get_db_connection(source_id, project_id=project_id)
    final_items = _get_ranked_list_items(conn, project_id, list_key)
    conn.close()
    final_items.sort(key=lambda x: x["rank"])
    
    # CRITICAL: Verify no duplicates by normalized form
    normalized_values = {}
    for item in final_items:
        normalized = normalize_rank_item(item["value_text"])
        if normalized in normalized_values:
            pytest.fail(
                f"Duplicate detected: '{item['value_text']}' (normalized: '{normalized}') "
                f"appears at ranks {normalized_values[normalized]['rank']} and {item['rank']}"
            )
        normalized_values[normalized] = item
    
    # Verify Breakfast Burritos appears exactly once at rank 2
    burritos_final = normalized_values.get(normalize_rank_item("breakfast burritos"))
    assert burritos_final is not None, "Breakfast Burritos should exist in final list"
    assert burritos_final["rank"] == 2, \
        f"Breakfast Burritos should be at rank 2, got rank {burritos_final['rank']}. " \
        f"Final list: {[(item['rank'], item['value_text']) for item in final_items]}"
    
    # Verify expected order: [Pancakes, Breakfast Burritos, Omelets, French Toast, Bagels]
    expected_order = ["pancakes", "breakfast burritos", "omelets", "french toast", "bagels"]
    assert len(final_items) == 5, f"Expected 5 items, got {len(final_items)}"
    
    for i, (item, expected_value) in enumerate(zip(final_items, expected_order), 1):
        normalized_item_value = normalize_rank_item(item["value_text"])
        normalized_expected = normalize_rank_item(expected_value)
        assert normalized_item_value == normalized_expected, \
            f"Rank {i}: expected '{expected_value}' (norm: '{normalized_expected}'), " \
            f"got '{item['value_text']}' (norm: '{normalized_item_value}')"
        assert item["rank"] == i, f"Item at position {i} should have rank {i}, got {item['rank']}"
    
    # Step 5: Verify invariants
    is_valid, error_msg = validate_ranked_list_invariants(final_items, list_key)
    assert is_valid, f"Ranked list invariants violated: {error_msg}"
    
    # Step 6: Verify via Facts-R retrieval (defensive deduplication should also work)
    # Extract canonical topic from list_key for retrieval
    from server.services.facts_normalize import extract_topic_from_list_key
    canonical_topic = extract_topic_from_list_key(list_key) or "weekend_breakfast"
    retrieved_facts = search_facts_ranked_list(
        project_id=project_id,
        topic_key=canonical_topic,
        limit=None
    )
    retrieved_facts.sort(key=lambda x: x.get("rank", 0))
    
    # Verify no duplicates in retrieval
    retrieved_normalized = {}
    for fact in retrieved_facts:
        normalized = normalize_rank_item(fact.get("value_text", ""))
        if normalized in retrieved_normalized:
            pytest.fail(
                f"Duplicate in retrieval: '{fact.get('value_text')}' (normalized: '{normalized}') "
                f"appears at ranks {retrieved_normalized[normalized].get('rank')} and {fact.get('rank')}"
            )
        retrieved_normalized[normalized] = fact
    
    # Verify Breakfast Burritos is at rank 2 in retrieval
    retrieved_burritos = retrieved_normalized.get(normalize_rank_item("breakfast burritos"))
    assert retrieved_burritos is not None, "Breakfast Burritos should exist in retrieval"
    assert retrieved_burritos.get("rank") == 2, \
        f"Breakfast Burritos should be at rank 2 in retrieval, got rank {retrieved_burritos.get('rank')}"


@pytest.mark.asyncio
async def test_rank_directive_respects_user_request(test_db_setup, test_thread_id):
    """
    Regression Test: "#2 favorite" must insert at rank 2, not default to rank 1.
    
    Scenario:
    - Seed list: [Pancakes, Omelets, French Toast]
    - Issue write: "My #2 favorite weekend breakfast is Waffles."
    - Assert: Waffles is at rank 2 (not rank 1)
    - Assert: List is [Pancakes, Waffles, Omelets, French Toast]
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Step 1: Seed initial ranked list
    seed_message = "My favorite weekend breakfasts are Pancakes, Omelets, French Toast."
    seed_result = await persist_facts_synchronously(
        project_id=project_id,
        message_content=seed_message,
        role="user",
        chat_id=test_thread_id,
        message_id=f"{test_thread_id}-user-1",
        timestamp=datetime.now(timezone.utc),
        message_index=0,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    assert seed_result.store_count == 3, f"Expected 3 items stored, got {seed_result.store_count}"
    
    # Step 2: Insert Waffles at rank 2
    mutation_message = "My #2 favorite weekend breakfast is Waffles."
    mutation_result = await persist_facts_synchronously(
        project_id=project_id,
        message_content=mutation_message,
        role="user",
        chat_id=test_thread_id,
        message_id=f"{test_thread_id}-user-2",
        timestamp=datetime.now(timezone.utc),
        message_index=1,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    
    # Step 3: Verify final list state
    # Use canonical_ranked_topic_key (single source of truth) for consistency
    from server.services.facts_normalize import canonical_ranked_topic_key
    list_key = canonical_ranked_topic_key("weekend breakfasts")
    conn = db.get_db_connection(source_id, project_id=project_id)
    final_items = _get_ranked_list_items(conn, project_id, list_key)
    conn.close()
    final_items.sort(key=lambda x: x["rank"])
    
    # Verify Waffles is at rank 2 (NOT rank 1)
    waffles_item = next((item for item in final_items if normalize_rank_item(item["value_text"]) == normalize_rank_item("Waffles")), None)
    assert waffles_item is not None, "Waffles should exist in final list"
    assert waffles_item["rank"] == 2, \
        f"Waffles should be at rank 2 (user requested #2), got rank {waffles_item['rank']}. " \
        f"This test FAILS if rank directive is ignored and defaults to rank 1."
    
    # Verify expected order: [Pancakes, Waffles, Omelets, French Toast]
    expected_order = ["pancakes", "waffles", "omelets", "french toast"]
    assert len(final_items) == 4, f"Expected 4 items, got {len(final_items)}"
    
    for i, (item, expected_value) in enumerate(zip(final_items, expected_order), 1):
        normalized_item_value = normalize_rank_item(item["value_text"])
        normalized_expected = normalize_rank_item(expected_value)
        assert normalized_item_value == normalized_expected, \
            f"Rank {i}: expected '{expected_value}' (norm: '{normalized_expected}'), " \
            f"got '{item['value_text']}' (norm: '{normalized_item_value}')"
        assert item["rank"] == i, f"Item at position {i} should have rank {i}, got {item['rank']}"


@pytest.mark.asyncio
async def test_case_insensitive_duplicate_prevention(test_db_setup, test_thread_id):
    """
    Regression Test: Case differences should not create duplicates.
    
    Scenario:
    - Seed list with "Breakfast Burritos" (capitalized)
    - Issue write: "My #2 favorite weekend breakfast is breakfast burritos." (lowercase)
    - Assert: No duplicate created, item moved to rank 2
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Step 1: Seed initial ranked list with capitalized "Breakfast Burritos"
    seed_message = "My favorite weekend breakfasts are Pancakes, Omelets, French Toast, Bagels, Breakfast Burritos."
    seed_result = await persist_facts_synchronously(
        project_id=project_id,
        message_content=seed_message,
        role="user",
        chat_id=test_thread_id,
        message_id=f"{test_thread_id}-user-1",
        timestamp=datetime.now(timezone.utc),
        message_index=0,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    assert seed_result.store_count == 5, f"Expected 5 items stored, got {seed_result.store_count}"
    
    # Step 2: Move using lowercase "breakfast burritos"
    mutation_message = "My #2 favorite weekend breakfast is breakfast burritos."
    mutation_result = await persist_facts_synchronously(
        project_id=project_id,
        message_content=mutation_message,
        role="user",
        chat_id=test_thread_id,
        message_id=f"{test_thread_id}-user-2",
        timestamp=datetime.now(timezone.utc),
        message_index=1,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    
    # Step 3: Verify no duplicates created
    # Find the actual list that was created (canonicalizer might normalize topic differently)
    conn = db.get_db_connection(source_id, project_id=project_id)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT fact_key 
        FROM project_facts 
        WHERE project_id = ? AND fact_key LIKE 'user.favorites.%' AND is_current = 1
        ORDER BY fact_key
    """, (project_id,))
    all_fact_keys = [row[0] for row in cursor.fetchall()]
    
    # Find the list key that contains our items (should have 5 items)
    list_key_counts = {}
    for fact_key in all_fact_keys:
        if '.' in fact_key:
            potential_list_key = '.'.join(fact_key.split('.')[:-1])
            list_key_counts[potential_list_key] = list_key_counts.get(potential_list_key, 0) + 1
    
    # Find list with 5 items
    list_key_final = None
    for list_key, count in list_key_counts.items():
        items = _get_ranked_list_items(conn, project_id, list_key)
        if len(items) == 5:
            list_key_final = list_key
            break
    
    assert list_key_final is not None, \
        f"Could not find list with 5 items. List key counts: {list_key_counts}"
    
    final_items = _get_ranked_list_items(conn, project_id, list_key_final)
    conn.close()
    final_items.sort(key=lambda x: x["rank"])
    
    # Count occurrences of "breakfast burritos" (normalized)
    burritos_count = sum(
        1 for item in final_items 
        if normalize_rank_item(item["value_text"]) == normalize_rank_item("breakfast burritos")
    )
    assert burritos_count == 1, \
        f"Breakfast Burritos should appear exactly once (case-insensitive), got {burritos_count} occurrences"
    
    # Verify it's at rank 2
    burritos_item = next(
        (item for item in final_items 
         if normalize_rank_item(item["value_text"]) == normalize_rank_item("breakfast burritos")),
        None
    )
    assert burritos_item is not None, "Breakfast Burritos should exist"
    assert burritos_item["rank"] == 2, \
        f"Breakfast Burritos should be at rank 2, got rank {burritos_item['rank']}"
    
    # Verify invariants
    is_valid, error_msg = validate_ranked_list_invariants(final_items, list_key_final)
    assert is_valid, f"Ranked list invariants violated: {error_msg}"

