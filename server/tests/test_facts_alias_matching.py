"""
Regression tests for alias/fuzzy matching in ranked list mutations.

Tests that partial/alias values (e.g., "rogue one") correctly match full canonical items
(e.g., "Star Wars: Rogue One") and that rank directives (#N) are always honored.
"""
import pytest
from datetime import datetime, timezone
from server.services.facts_persistence import persist_facts_synchronously
from server.services.facts_apply import validate_ranked_list_invariants, _get_ranked_list_items, normalize_rank_item, resolve_ranked_item_target
from server.services.facts_normalize import canonical_list_key
from server.services.canonicalizer import canonicalize_topic
from memory_service.memory_dashboard import db


@pytest.mark.asyncio
async def test_alias_move_star_wars_rogue_one(test_db_setup, test_thread_id):
    """
    Regression Test: Partial "rogue one" should move existing "Star Wars: Rogue One".
    
    Bug: User says "My #2 favorite sci-fi movie is rogue one" but it doesn't match
    existing "Star Wars: Rogue One" and either creates a duplicate or doesn't move it.
    
    Scenario:
    - Seed list with "Star Wars: Rogue One" at rank 8
    - Issue write: "My #2 favorite sci-fi movie is rogue one."
    - Assert: "Star Wars: Rogue One" is moved to rank 2 (not inserted as new item)
    - Assert: No duplicate created
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Step 1: Seed initial ranked list with "Star Wars: Rogue One" at rank 8
    seed_message = "My favorite sci-fi movies are Interstellar, The Matrix, Arrival, Blade Runner 2049, Dune (2021), Alien, Ex Machina, Star Wars: Rogue One, Edge of Tomorrow."
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
    assert seed_result.store_count == 9, f"Expected 9 items stored, got {seed_result.store_count}"
    
    # Verify initial state - find the actual canonical topic used
    # The canonicalizer might normalize "sci-fi movies" to "scifi_movie" or "movie"
    # Let's search for all ranked lists and find the one with our items
    conn = db.get_db_connection(source_id, project_id=project_id)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT fact_key 
        FROM project_facts 
        WHERE project_id = ? AND fact_key LIKE 'user.favorites.%' AND is_current = 1
        ORDER BY fact_key
    """, (project_id,))
    all_fact_keys = [row[0] for row in cursor.fetchall()]
    
    # Find the list key that contains our items (should have 9 items)
    # Group fact keys by list (everything before the last dot)
    list_key_counts = {}
    for fact_key in all_fact_keys:
        if '.' in fact_key:
            potential_list_key = '.'.join(fact_key.split('.')[:-1])
            list_key_counts[potential_list_key] = list_key_counts.get(potential_list_key, 0) + 1
    
    # Find list with 9 items
    list_key_seed = None
    for list_key, count in list_key_counts.items():
        items = _get_ranked_list_items(conn, project_id, list_key)
        if len(items) == 9:
            list_key_seed = list_key
            break
    
    assert list_key_seed is not None, \
        f"Could not find list with 9 items. List key counts: {list_key_counts}"
    
    # Get initial items
    initial_items = _get_ranked_list_items(conn, project_id, list_key_seed)
    conn.close()
    initial_items.sort(key=lambda x: x["rank"])
    
    # Verify "Star Wars: Rogue One" is at rank 8 initially
    rogue_one_initial = next(
        (item for item in initial_items 
         if normalize_rank_item(item["value_text"]) == normalize_rank_item("Star Wars: Rogue One")),
        None
    )
    assert rogue_one_initial is not None, \
        f"Star Wars: Rogue One should exist in initial list. " \
        f"Items found: {[(item['rank'], item['value_text']) for item in initial_items]}"
    assert rogue_one_initial["rank"] == 8, \
        f"Star Wars: Rogue One should be at rank 8 initially, got {rogue_one_initial['rank']}"
    
    # Step 2: Move using partial/alias "rogue one" to rank 2
    # Use same topic as seed (plural) to ensure we're looking in the same list
    mutation_message = "My #2 favorite sci-fi movies is rogue one."
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
    
    # Step 3: Verify mutation result - should be a MOVE, not INSERT
    assert mutation_result.update_count >= 1 or mutation_result.store_count >= 1, \
        f"Should have at least 1 update or store (Star Wars: Rogue One moved/inserted). " \
        f"update_count={mutation_result.update_count}, store_count={mutation_result.store_count}"
    
    # Check rank_mutations to verify it was a MOVE, not INSERT (if available)
    mutation_info = None
    if mutation_result.rank_mutations:
        for fact_key, info in mutation_result.rank_mutations.items():
            if "rogue" in info.get("value", "").lower() or "rogue" in fact_key.lower():
                mutation_info = info
                break
        
        if mutation_info:
            assert mutation_info["action"] == "move", \
                f"Expected MOVE action (alias match), got {mutation_info['action']}. " \
                f"This test FAILS if alias matching doesn't work and it creates a new item instead. " \
                f"Mutation info: {mutation_info}"
            assert mutation_info["old_rank"] == 8, \
                f"Expected old_rank=8, got {mutation_info['old_rank']}"
            assert mutation_info["new_rank"] == 2, \
                f"Expected new_rank=2 (user specified #2), got {mutation_info['new_rank']}. " \
                f"This test FAILS if rank directive is not honored."
    
    # Step 4: Verify final list state
    # Use the same list_key as seed (should be the same topic)
    conn = db.get_db_connection(source_id, project_id=project_id)
    final_items = _get_ranked_list_items(conn, project_id, list_key_seed)
    conn.close()
    final_items.sort(key=lambda x: x["rank"])
    
    # Verify no duplicates
    normalized_values = {}
    for item in final_items:
        normalized = normalize_rank_item(item["value_text"])
        if normalized in normalized_values:
            pytest.fail(
                f"Duplicate detected: '{item['value_text']}' (normalized: '{normalized}') "
                f"appears at ranks {normalized_values[normalized]['rank']} and {item['rank']}"
            )
        normalized_values[normalized] = item
    
    # Verify "Star Wars: Rogue One" is at rank 2
    rogue_one_final = normalized_values.get(normalize_rank_item("star wars: rogue one"))
    assert rogue_one_final is not None, "Star Wars: Rogue One should exist in final list"
    assert rogue_one_final["rank"] == 2, \
        f"Star Wars: Rogue One should be at rank 2 (user specified #2), got rank {rogue_one_final['rank']}. " \
        f"Final items: {[(item['rank'], item['value_text']) for item in final_items]}"
    
    # Verify invariants
    is_valid, error_msg = validate_ranked_list_invariants(final_items, list_key)
    assert is_valid, f"Ranked list invariants violated: {error_msg}"


@pytest.mark.asyncio
async def test_rank_override_from_user_text(test_db_setup, test_thread_id):
    """
    Regression Test: "#2 favorite" must NEVER become rank 1.
    
    Bug: User says "My #2 favorite X is Y" but system inserts at rank 1 or ignores the rank.
    
    Scenario:
    - Seed list: [Item1, Item2, Item3]
    - Issue write: "My #2 favorite topic is NewItem."
    - Assert: NewItem is at rank 2 (NOT rank 1)
    - Assert: List is [Item1, NewItem, Item2, Item3] (Item2 and Item3 shifted down)
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Step 1: Seed initial ranked list
    seed_message = "My favorite test items are Item1, Item2, Item3."
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
    
    # Step 2: Insert NewItem at rank 2 (user explicitly says #2)
    mutation_message = "My #2 favorite test item is NewItem."
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
    # Note: rank_mutations comes from the ApplyResult inside PersistFactsResult
    # Check if the apply result has rank_mutations
    if not hasattr(mutation_result, 'rank_mutations') or mutation_result.rank_mutations is None:
        pytest.fail(
            f"rank_mutations is None or missing. "
            f"store_count={mutation_result.store_count}, update_count={mutation_result.update_count}. "
            f"This might indicate the mutation didn't happen or there was an error."
        )
    
    mutation_info = None
    for fact_key, info in mutation_result.rank_mutations.items():
        if "newitem" in info.get("value", "").lower():
            mutation_info = info
            break
    
    assert mutation_info is not None, \
        f"Should have rank mutation info for NewItem. " \
        f"Available mutations: {list(mutation_result.rank_mutations.keys())}"
    assert mutation_info["new_rank"] == 2, \
        f"CRITICAL: User specified #2, but new_rank={mutation_info['new_rank']}. " \
        f"This test FAILS if rank directive is not honored. " \
        f"Mutation info: {mutation_info}"
    assert mutation_info["new_rank"] != 1, \
        f"CRITICAL: User specified #2, but got rank 1. This is the exact bug being fixed."
    
    # Step 4: Verify final list state
    canonical_topic = canonicalize_topic("test items", invoke_teacher=False).canonical_topic
    list_key = canonical_list_key(canonical_topic)
    conn = db.get_db_connection(source_id, project_id=project_id)
    final_items = _get_ranked_list_items(conn, project_id, list_key)
    conn.close()
    final_items.sort(key=lambda x: x["rank"])
    
    # Verify NewItem is at rank 2 (NOT rank 1)
    newitem_item = next(
        (item for item in final_items 
         if normalize_rank_item(item["value_text"]) == normalize_rank_item("NewItem")),
        None
    )
    assert newitem_item is not None, "NewItem should exist in final list"
    assert newitem_item["rank"] == 2, \
        f"CRITICAL: User specified #2, but NewItem is at rank {newitem_item['rank']}. " \
        f"This test FAILS if rank directive is not honored. " \
        f"Final items: {[(item['rank'], item['value_text']) for item in final_items]}"
    assert newitem_item["rank"] != 1, \
        f"CRITICAL: User specified #2, but NewItem is at rank 1. This is the exact bug."
    
    # Verify expected order: [Item1, NewItem, Item2, Item3]
    expected_order = ["item1", "newitem", "item2", "item3"]
    assert len(final_items) == 4, f"Expected 4 items, got {len(final_items)}"
    
    for i, (item, expected_value) in enumerate(zip(final_items, expected_order), 1):
        normalized_item_value = normalize_rank_item(item["value_text"])
        normalized_expected = normalize_rank_item(expected_value)
        assert normalized_item_value == normalized_expected, \
            f"Rank {i}: expected '{expected_value}' (norm: '{normalized_expected}'), " \
            f"got '{item['value_text']}' (norm: '{normalized_item_value}')"
        assert item["rank"] == i, f"Item at position {i} should have rank {i}, got {item['rank']}"


@pytest.mark.asyncio
async def test_alias_move_breath_of_the_wild(test_db_setup, test_thread_id):
    """
    Regression Test: Partial "breath of the wild" should match "The Legend of Zelda: Breath of the Wild".
    
    Scenario:
    - Seed list with "The Legend of Zelda: Breath of the Wild" at rank 5
    - Issue write: "My #1 favorite game is breath of the wild."
    - Assert: "The Legend of Zelda: Breath of the Wild" is moved to rank 1
    - Assert: No duplicate created
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Step 1: Seed initial ranked list
    seed_message = "My favorite games are Game1, Game2, Game3, Game4, The Legend of Zelda: Breath of the Wild, Game6."
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
    assert seed_result.store_count == 6, f"Expected 6 items stored, got {seed_result.store_count}"
    
    # Step 2: Move using partial "breath of the wild" to rank 1
    mutation_message = "My #1 favorite game is breath of the wild."
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
    assert mutation_result.update_count >= 1, "Should have at least 1 update"
    
    # Check rank_mutations
    mutation_info = None
    for fact_key, info in mutation_result.rank_mutations.items():
        if "zelda" in info.get("value", "").lower() or "breath" in info.get("value", "").lower():
            mutation_info = info
            break
    
    assert mutation_info is not None, "Should have rank mutation info"
    assert mutation_info["action"] == "move", \
        f"Expected MOVE action, got {mutation_info['action']}"
    assert mutation_info["new_rank"] == 1, \
        f"Expected new_rank=1 (user specified #1), got {mutation_info['new_rank']}"
    
    # Step 4: Verify final list state
    canonical_topic = canonicalize_topic("games", invoke_teacher=False).canonical_topic
    list_key = canonical_list_key(canonical_topic)
    conn = db.get_db_connection(source_id, project_id=project_id)
    final_items = _get_ranked_list_items(conn, project_id, list_key)
    conn.close()
    final_items.sort(key=lambda x: x["rank"])
    
    # Verify "The Legend of Zelda: Breath of the Wild" is at rank 1
    zelda_item = next(
        (item for item in final_items 
         if "zelda" in normalize_rank_item(item["value_text"]) or "breath" in normalize_rank_item(item["value_text"])),
        None
    )
    assert zelda_item is not None, "Zelda game should exist in final list"
    assert zelda_item["rank"] == 1, \
        f"Zelda game should be at rank 1, got rank {zelda_item['rank']}"
    
    # Verify no duplicates
    normalized_values = {}
    for item in final_items:
        normalized = normalize_rank_item(item["value_text"])
        if normalized in normalized_values:
            pytest.fail(f"Duplicate detected: '{item['value_text']}' at ranks {normalized_values[normalized]['rank']} and {item['rank']}")
        normalized_values[normalized] = item
    
    # Verify invariants
    is_valid, error_msg = validate_ranked_list_invariants(final_items, list_key)
    assert is_valid, f"Ranked list invariants violated: {error_msg}"


@pytest.mark.asyncio
async def test_resolve_ranked_item_target_unit(test_db_setup):
    """
    Unit test for resolve_ranked_item_target function.
    
    Tests fuzzy/alias matching logic directly.
    """
    # Test data
    existing_items = [
        {"value_text": "Star Wars: Rogue One", "rank": 8, "fact_key": "test.8"},
        {"value_text": "The Matrix", "rank": 2, "fact_key": "test.2"},
        {"value_text": "Interstellar", "rank": 1, "fact_key": "test.1"},
    ]
    
    # Test 1: Exact match
    result = resolve_ranked_item_target("The Matrix", existing_items)
    assert result is not None, "Exact match should work"
    assert result["value_text"] == "The Matrix"
    assert result["rank"] == 2
    
    # Test 2: Partial match - "rogue one" → "Star Wars: Rogue One"
    result = resolve_ranked_item_target("rogue one", existing_items)
    assert result is not None, "Partial match 'rogue one' should match 'Star Wars: Rogue One'"
    assert result["value_text"] == "Star Wars: Rogue One"
    assert result["rank"] == 8
    
    # Test 3: No match
    result = resolve_ranked_item_target("Nonexistent Movie", existing_items)
    assert result is None, "Non-matching value should return None"
    
    # Test 4: Case-insensitive partial match
    result = resolve_ranked_item_target("ROGUE ONE", existing_items)
    assert result is not None, "Case-insensitive partial match should work"
    assert result["value_text"] == "Star Wars: Rogue One"

