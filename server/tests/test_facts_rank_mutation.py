"""
Integration tests for ranked list mutation operations (MOVE, INSERT, NO-OP).

Tests the behavior of explicit rank mutations like:
- "My #2 favorite vacation destination is Thailand."
"""
import pytest
from datetime import datetime, timezone
from server.services.facts_persistence import persist_facts_synchronously
from server.services.facts_apply import validate_ranked_list_invariants, _get_ranked_list_items, normalize_favorite_value
from server.services.facts_normalize import canonical_list_key
from server.services.canonicalizer import canonicalize_topic
from memory_service.memory_dashboard import db


@pytest.mark.asyncio
async def test_move_existing_value_upward(test_db_setup, test_thread_id):
    """
    Case A: MOVE existing value upward.
    
    Seed list: [japan, italy, new zealand, spain, greece, thailand, portugal]
    Input: "My #2 favorite vacation destination is Thailand."
    Expected: [japan, thailand, italy, new zealand, spain, greece, portugal]
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Step 1: Seed initial ranked list
    seed_message = "My favorite vacation destinations are Japan, Italy, New Zealand, Spain, Greece, Thailand, Portugal."
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
    assert seed_result.store_count == 7, f"Expected 7 items stored, got {seed_result.store_count}"
    
    # Step 2: Move Thailand from rank 6 to rank 2
    mutation_message = "My #2 favorite vacation destination is Thailand."
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
    # Should have updated Thailand (move) + shifted items (italy, new zealand, spain, greece)
    assert mutation_result.update_count >= 1, "Should have at least 1 update (Thailand moved)"
    
    # Step 4: Verify final list state
    canonical_topic = canonicalize_topic("vacation destination", invoke_teacher=False).canonical_topic
    list_key = canonical_list_key(canonical_topic)
    
    conn = db.get_db_connection(source_id, project_id=project_id)
    items = _get_ranked_list_items(conn, project_id, list_key)
    conn.close()
    
    # Sort by rank
    items.sort(key=lambda x: x["rank"])
    
    # Verify expected order
    expected_order = ["japan", "thailand", "italy", "new zealand", "spain", "greece", "portugal"]
    assert len(items) == 7, f"Expected 7 items, got {len(items)}"
    
    for i, (item, expected_value) in enumerate(zip(items, expected_order), 1):
        normalized_item_value = normalize_favorite_value(item["value_text"])
        normalized_expected = normalize_favorite_value(expected_value)
        assert normalized_item_value == normalized_expected, \
            f"Rank {i}: expected '{expected_value}' (norm: '{normalized_expected}'), " \
            f"got '{item['value_text']}' (norm: '{normalized_item_value}')"
        assert item["rank"] == i, f"Item at position {i} should have rank {i}, got {item['rank']}"
    
    # Step 5: Verify invariants
    is_valid, error_msg = validate_ranked_list_invariants(items, list_key)
    assert is_valid, f"Ranked list invariants violated: {error_msg}"


@pytest.mark.asyncio
async def test_move_existing_value_downward(test_db_setup, test_thread_id):
    """
    Case B: MOVE existing value downward.
    
    Seed list: [japan, thailand, italy, new zealand, spain, greece, portugal]
    Input: "My #6 favorite vacation destination is Italy."
    Expected: [japan, thailand, new zealand, spain, greece, italy, portugal]
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Step 1: Seed initial ranked list (using result from previous test's expected state)
    seed_message = "My favorite vacation destinations are Japan, Thailand, Italy, New Zealand, Spain, Greece, Portugal."
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
    assert seed_result.store_count == 7
    
    # Step 2: Move Italy from rank 3 to rank 6
    mutation_message = "My #6 favorite vacation destination is Italy."
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
    canonical_topic = canonicalize_topic("vacation destination", invoke_teacher=False).canonical_topic
    list_key = canonical_list_key(canonical_topic)
    
    conn = db.get_db_connection(source_id, project_id=project_id)
    items = _get_ranked_list_items(conn, project_id, list_key)
    conn.close()
    
    items.sort(key=lambda x: x["rank"])
    
    expected_order = ["japan", "thailand", "new zealand", "spain", "greece", "italy", "portugal"]
    assert len(items) == 7
    
    for i, (item, expected_value) in enumerate(zip(items, expected_order), 1):
        normalized_item_value = normalize_favorite_value(item["value_text"])
        normalized_expected = normalize_favorite_value(expected_value)
        assert normalized_item_value == normalized_expected, \
            f"Rank {i}: expected '{expected_value}', got '{item['value_text']}'"
        assert item["rank"] == i
    
    # Verify invariants
    is_valid, error_msg = validate_ranked_list_invariants(items, list_key)
    assert is_valid, f"Ranked list invariants violated: {error_msg}"


@pytest.mark.asyncio
async def test_already_at_rank_noop(test_db_setup, test_thread_id):
    """
    Case C: Already at rank (NO-OP messaging).
    
    Seed list: [japan, italy, new zealand, ...]
    Input: "My #2 favorite vacation destination is Italy."
    Expected: list unchanged + response indicates already #2
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Step 1: Seed initial ranked list
    seed_message = "My favorite vacation destinations are Japan, Italy, New Zealand."
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
    assert seed_result.store_count == 3
    
    # Step 2: Get initial state
    canonical_topic = canonicalize_topic("vacation destination", invoke_teacher=False).canonical_topic
    list_key = canonical_list_key(canonical_topic)
    
    conn = db.get_db_connection(source_id, project_id=project_id)
    initial_items = _get_ranked_list_items(conn, project_id, list_key)
    conn.close()
    initial_items.sort(key=lambda x: x["rank"])
    
    # Step 3: Try to set Italy at rank 2 (where it already is)
    mutation_message = "My #2 favorite vacation destination is Italy."
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
    
    # Step 4: Verify NO-OP (no store, no update)
    # Note: The mutation function returns NO-OP, but we may still have some counts
    # The key is that the list state is unchanged
    
    # Step 5: Verify list unchanged
    conn = db.get_db_connection(source_id, project_id=project_id)
    final_items = _get_ranked_list_items(conn, project_id, list_key)
    conn.close()
    final_items.sort(key=lambda x: x["rank"])
    
    assert len(final_items) == len(initial_items), "List length should be unchanged"
    for initial, final in zip(initial_items, final_items):
        assert normalize_favorite_value(initial["value_text"]) == normalize_favorite_value(final["value_text"]), \
            f"Value at rank {initial['rank']} changed: '{initial['value_text']}' -> '{final['value_text']}'"
        assert initial["rank"] == final["rank"]


@pytest.mark.asyncio
async def test_insert_new_value_at_rank(test_db_setup, test_thread_id):
    """
    Case D: INSERT new value at rank.
    
    Seed list: [japan, italy, new zealand, spain, greece, thailand, portugal]
    Input: "My #2 favorite vacation destination is Canada."
    Expected: [japan, canada, italy, new zealand, spain, greece, thailand, portugal]
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Step 1: Seed initial ranked list
    seed_message = "My favorite vacation destinations are Japan, Italy, New Zealand, Spain, Greece, Thailand, Portugal."
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
    assert seed_result.store_count == 7
    
    # Step 2: Insert Canada at rank 2
    mutation_message = "My #2 favorite vacation destination is Canada."
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
    assert mutation_result.store_count >= 1, "Should have at least 1 store (Canada inserted)"
    assert mutation_result.update_count >= 6, "Should have 6 updates (items shifted)"
    
    # Step 4: Verify final list state
    canonical_topic = canonicalize_topic("vacation destination", invoke_teacher=False).canonical_topic
    list_key = canonical_list_key(canonical_topic)
    
    conn = db.get_db_connection(source_id, project_id=project_id)
    items = _get_ranked_list_items(conn, project_id, list_key)
    conn.close()
    
    items.sort(key=lambda x: x["rank"])
    
    expected_order = ["japan", "canada", "italy", "new zealand", "spain", "greece", "thailand", "portugal"]
    assert len(items) == 8, f"Expected 8 items, got {len(items)}"
    
    for i, (item, expected_value) in enumerate(zip(items, expected_order), 1):
        normalized_item_value = normalize_favorite_value(item["value_text"])
        normalized_expected = normalize_favorite_value(expected_value)
        assert normalized_item_value == normalized_expected, \
            f"Rank {i}: expected '{expected_value}', got '{item['value_text']}'"
        assert item["rank"] == i
    
    # Verify invariants
    is_valid, error_msg = validate_ranked_list_invariants(items, list_key)
    assert is_valid, f"Ranked list invariants violated: {error_msg}"


@pytest.mark.asyncio
async def test_rank_beyond_length_append(test_db_setup, test_thread_id):
    """
    Case E: Rank beyond length (append to end).
    
    Seed list: [japan, italy, new zealand]
    Input: "My #999 favorite vacation destination is Morocco."
    Expected: [japan, italy, new zealand, morocco] (appended at rank 4)
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Step 1: Seed initial ranked list
    seed_message = "My favorite vacation destinations are Japan, Italy, New Zealand."
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
    assert seed_result.store_count == 3
    
    # Step 2: Try to set Morocco at rank 999 (should append to end)
    mutation_message = "My #999 favorite vacation destination is Morocco."
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
    canonical_topic = canonicalize_topic("vacation destination", invoke_teacher=False).canonical_topic
    list_key = canonical_list_key(canonical_topic)
    
    conn = db.get_db_connection(source_id, project_id=project_id)
    items = _get_ranked_list_items(conn, project_id, list_key)
    conn.close()
    
    items.sort(key=lambda x: x["rank"])
    
    expected_order = ["japan", "italy", "new zealand", "morocco"]
    assert len(items) == 4, f"Expected 4 items, got {len(items)}"
    
    for i, (item, expected_value) in enumerate(zip(items, expected_order), 1):
        normalized_item_value = normalize_favorite_value(item["value_text"])
        normalized_expected = normalize_favorite_value(expected_value)
        assert normalized_item_value == normalized_expected, \
            f"Rank {i}: expected '{expected_value}', got '{item['value_text']}'"
        assert item["rank"] == i
    
    # Verify invariants
    is_valid, error_msg = validate_ranked_list_invariants(items, list_key)
    assert is_valid, f"Ranked list invariants violated: {error_msg}"


@pytest.mark.asyncio
async def test_rank_mutation_e2e_integration(test_db_setup, test_thread_id):
    """
    Full E2E integration test: seed, move, insert, verify query.
    
    This test reproduces the exact bug scenario from the UI:
    1. Seed list with 7 items
    2. Move Thailand to rank 2
    3. Query "What is my second favorite vacation destination?"
    4. Verify it returns Thailand
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Step 1: Seed initial ranked list
    seed_message = "My favorite vacation destinations are Japan, Italy, New Zealand, Spain, Greece, Thailand, Portugal."
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
    assert seed_result.store_count == 7
    
    # Step 2: Move Thailand to rank 2 (reproducing the bug scenario)
    mutation_message = "My #2 favorite vacation destination is Thailand."
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
    canonical_topic = canonicalize_topic("vacation destination", invoke_teacher=False).canonical_topic
    list_key = canonical_list_key(canonical_topic)
    
    conn = db.get_db_connection(source_id, project_id=project_id)
    items = _get_ranked_list_items(conn, project_id, list_key)
    conn.close()
    
    items.sort(key=lambda x: x["rank"])
    
    # Step 4: Verify Thailand is at rank 2
    assert len(items) >= 2, "List should have at least 2 items"
    rank_2_item = next((item for item in items if item["rank"] == 2), None)
    assert rank_2_item is not None, "Rank 2 item should exist"
    
    normalized_rank_2_value = normalize_favorite_value(rank_2_item["value_text"])
    normalized_thailand = normalize_favorite_value("Thailand")
    assert normalized_rank_2_value == normalized_thailand, \
        f"Rank 2 should be 'Thailand', got '{rank_2_item['value_text']}'"
    
    # Step 5: Verify invariants
    is_valid, error_msg = validate_ranked_list_invariants(items, list_key)
    assert is_valid, f"Ranked list invariants violated: {error_msg}"

