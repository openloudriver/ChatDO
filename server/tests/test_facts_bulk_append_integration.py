"""
Integration tests for bulk preference append operations.

Tests the full pipeline: persist_facts_synchronously -> apply_facts_ops -> DB storage.
Reproduces the v70 failure scenario and verifies fixes.

Uses shared fixtures from conftest.py for database setup.
"""
import pytest
import re
from datetime import datetime, timezone
from server.services.facts_persistence import persist_facts_synchronously
from server.services.facts_apply import validate_ranked_list_invariants
from server.services.facts_normalize import canonical_list_key
from server.services.canonicalizer import canonicalize_topic
from memory_service.memory_dashboard import db


@pytest.mark.asyncio
async def test_bulk_append_initial_list(test_db_setup, test_thread_id):
    """
    Test 1: Initial bulk write creates ranked list.
    
    Input: "My favorite book genres are Sci-Fi, Fantasy, and History."
    Expected: Ranks 1..3 stored, no duplicates, no Facts-F.
    """
    project_id = test_db_setup["project_id"]
    message_content = "My favorite book genres are Sci-Fi, Fantasy, and History."
    message_id = f"{test_thread_id}-user-1"
    timestamp = datetime.now(timezone.utc)
    
    result = await persist_facts_synchronously(
        project_id=project_id,
        message_content=message_content,
        role="user",
        chat_id=test_thread_id,
        message_id=message_id,
        timestamp=timestamp,
        message_index=0,
        write_intent_detected=True,
        routing_plan_candidate=None  # Let safety net handle it
    )
    
    # Assertions
    assert result.store_count == 3, f"Expected 3 stored, got {result.store_count}"
    assert result.update_count == 0, f"Expected 0 updated, got {result.update_count}"
    assert result.duplicate_blocked is None or len(result.duplicate_blocked) == 0
    assert len(result.stored_fact_keys) == 3, f"Expected 3 fact keys, got {len(result.stored_fact_keys)}"
    
    # Verify ranks are 1, 2, 3
    ranks = []
    for fact_key in result.stored_fact_keys:
        # Extract rank from fact_key (e.g., "user.favorites.book_genre.1" -> 1)
        match = re.match(r'^user\.favorites\.(.+)\.(\d+)$', fact_key)
        if match:
            rank = int(match.group(2))
            ranks.append(rank)
    
    assert sorted(ranks) == [1, 2, 3], f"Expected ranks [1,2,3], got {sorted(ranks)}"
    
    # Verify values are stored correctly
    source_id = test_db_setup["source_id"]
    for fact_key in result.stored_fact_keys:
        fact = db.get_current_fact(project_id=project_id, fact_key=fact_key)
        assert fact is not None, f"Fact {fact_key} not found in DB"
        # Values may be normalized (lowercase), so check case-insensitively
        value_lower = fact.get("value_text", "").lower()
        assert value_lower in ["sci-fi", "fantasy", "history"], \
            f"Unexpected value: {fact.get('value_text')}"


@pytest.mark.asyncio
async def test_bulk_append_to_existing_list(test_db_setup, test_thread_id):
    """
    Test 2: Bulk append to existing ranked list (v70 failure scenario).
    
    Setup: Existing list with Sci-Fi, Fantasy, History
    Input: "My favorite book genres are Mystery, Biography, and Fantasy."
    Expected:
    - Mystery appended at #4
    - Biography appended at #5
    - Fantasy skipped as duplicate at #2
    - No Facts-F response
    """
    project_id = test_db_setup["project_id"]
    
    # Step 1: Create initial list
    message_1 = "My favorite book genres are Sci-Fi, Fantasy, and History."
    message_id_1 = f"{test_thread_id}-user-1"
    timestamp_1 = datetime.now(timezone.utc)
    
    result_1 = await persist_facts_synchronously(
        project_id=project_id,
        message_content=message_1,
        role="user",
        chat_id=test_thread_id,
        message_id=message_id_1,
        timestamp=timestamp_1,
        message_index=0,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    
    assert result_1.store_count == 3, "Initial list creation failed"
    
    # Step 2: Append to existing list (the v70 failure case)
    message_2 = "My favorite book genres are Mystery, Biography, and Fantasy."
    message_id_2 = f"{test_thread_id}-user-2"
    timestamp_2 = datetime.now(timezone.utc)
    
    result_2 = await persist_facts_synchronously(
        project_id=project_id,
        message_content=message_2,
        role="user",
        chat_id=test_thread_id,
        message_id=message_id_2,
        timestamp=timestamp_2,
        message_index=1,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    
    # Assertions for second write
    assert result_2.store_count == 2, f"Expected 2 new items (Mystery, Biography), got {result_2.store_count}"
    assert result_2.update_count == 0
    assert result_2.duplicate_blocked is not None, "Expected Fantasy to be blocked as duplicate"
    assert len(result_2.duplicate_blocked) == 1, f"Expected 1 duplicate, got {len(result_2.duplicate_blocked)}"
    
    # Verify duplicate info (duplicate_blocked uses normalized lowercase keys)
    fantasy_info = result_2.duplicate_blocked.get("fantasy")
    assert fantasy_info is not None, "Fantasy should be in duplicate_blocked (normalized key: 'fantasy')"
    assert fantasy_info["existing_rank"] == 2, f"Fantasy should be at rank 2, got {fantasy_info['existing_rank']}"
    
    # Verify new items are at ranks 4 and 5
    ranks = []
    values_by_rank = {}
    for fact_key in result_2.stored_fact_keys:
        match = re.match(r'^user\.favorites\.(.+)\.(\d+)$', fact_key)
        if match:
            rank = int(match.group(2))
            ranks.append(rank)
            fact = db.get_current_fact(project_id=project_id, fact_key=fact_key)
            if fact:
                values_by_rank[rank] = fact.get("value_text", "")
    
    assert 4 in ranks, "Mystery should be at rank 4"
    assert 5 in ranks, "Biography should be at rank 5"
    # Values may be normalized to lowercase
    val_4 = values_by_rank.get(4, "").lower() if values_by_rank.get(4) else ""
    val_5 = values_by_rank.get(5, "").lower() if values_by_rank.get(5) else ""
    assert val_4 == "mystery" or val_5 == "mystery", "Mystery not found at rank 4 or 5"
    assert val_4 == "biography" or val_5 == "biography", "Biography not found at rank 4 or 5"
    
    # Verify final list state: query all facts for book_genre
    conn = db.get_db_connection(test_db_setup["source_id"], project_id=project_id)
    cursor = conn.cursor()
    
    canonicalization_result = canonicalize_topic("book genres", invoke_teacher=False)
    canonical_topic = canonicalization_result.canonical_topic
    list_key = canonical_list_key(canonical_topic)
    
    cursor.execute("""
        SELECT fact_key, value_text
        FROM project_facts
        WHERE project_id = ? AND fact_key LIKE ? AND is_current = 1
        ORDER BY fact_key
    """, (project_id, f"{list_key}.%"))
    
    rows = cursor.fetchall()
    items = []
    for row in rows:
        fact_key = row[0]
        value_text = row[1] if len(row) > 1 else ""
        if "." in fact_key:
            try:
                rank_str = fact_key.rsplit(".", 1)[1]
                rank = int(rank_str)
                items.append({
                    "fact_key": fact_key,
                    "rank": rank,
                    "value_text": value_text
                })
            except (ValueError, IndexError):
                continue
    
    conn.close()
    
    # Verify we have 5 facts total (3 initial + 2 new)
    assert len(items) == 5, f"Expected 5 facts total, got {len(items)}"
    
    # Verify Fantasy appears only once (at rank 2) - case-insensitive
    fantasy_count = sum(1 for item in items if item.get("value_text", "").lower() == "fantasy")
    assert fantasy_count == 1, f"Fantasy should appear exactly once, found {fantasy_count} times"
    
    # Verify ordering: Sci-Fi, Fantasy, History, Mystery, Biography (case-insensitive)
    sorted_items = sorted(items, key=lambda f: f.get("rank", 0))
    values = [item.get("value_text", "").lower() for item in sorted_items]
    assert "sci-fi" in values, "Sci-Fi should be in list"
    assert "fantasy" in values, "Fantasy should be in list"
    assert "history" in values, "History should be in list"
    assert "mystery" in values, "Mystery should be in list"
    assert "biography" in values, "Biography should be in list"
    
    # Verify ranked list invariants
    is_valid, error_msg = validate_ranked_list_invariants(items, list_key)
    assert is_valid, f"Ranked list invariants violated: {error_msg}"


@pytest.mark.asyncio
async def test_bulk_append_only_duplicates(test_db_setup, test_thread_id):
    """
    Test 3: Bulk append with only duplicates.
    
    Setup: Existing list with Sci-Fi, Fantasy, History
    Input: "My favorite book genres are Fantasy, History."
    Expected:
    - Both items skipped as duplicates
    - Returns success message (not Facts-F)
    - duplicate_blocked contains both items
    """
    project_id = test_db_setup["project_id"]
    
    # Step 1: Create initial list
    message_1 = "My favorite book genres are Sci-Fi, Fantasy, and History."
    result_1 = await persist_facts_synchronously(
        project_id=project_id,
        message_content=message_1,
        role="user",
        chat_id=test_thread_id,
        message_id=f"{test_thread_id}-user-1",
        timestamp=datetime.now(timezone.utc),
        message_index=0,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    
    assert result_1.store_count == 3
    
    # Step 2: Try to append only duplicates
    message_2 = "My favorite book genres are Fantasy, History."
    result_2 = await persist_facts_synchronously(
        project_id=project_id,
        message_content=message_2,
        role="user",
        chat_id=test_thread_id,
        message_id=f"{test_thread_id}-user-2",
        timestamp=datetime.now(timezone.utc),
        message_index=1,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    
    # Assertions
    assert result_2.store_count == 0, "No new items should be stored"
    assert result_2.update_count == 0
    assert result_2.duplicate_blocked is not None, "Duplicates should be blocked"
    assert len(result_2.duplicate_blocked) == 2, f"Expected 2 duplicates, got {len(result_2.duplicate_blocked)}"
    
    # Verify both items are in duplicate_blocked (using normalized lowercase keys)
    assert "fantasy" in result_2.duplicate_blocked, "Fantasy should be blocked (normalized key: 'fantasy')"
    assert "history" in result_2.duplicate_blocked, "History should be blocked (normalized key: 'history')"
    
    # Verify existing ranks
    fantasy_info = result_2.duplicate_blocked["fantasy"]
    history_info = result_2.duplicate_blocked["history"]
    assert fantasy_info["existing_rank"] == 2, "Fantasy should be at rank 2"
    assert history_info["existing_rank"] == 3, "History should be at rank 3"


@pytest.mark.asyncio
async def test_bulk_append_no_oxford_comma(test_db_setup, test_thread_id):
    """
    Test 4: Bulk append without Oxford comma.
    
    Input: "My favorite book genres are Mystery, Biography and Fantasy."
    Expected: Same behavior as with Oxford comma (3 items parsed correctly)
    """
    project_id = test_db_setup["project_id"]
    
    # Create initial list
    message_1 = "My favorite book genres are Sci-Fi, Fantasy, and History."
    await persist_facts_synchronously(
        project_id=project_id,
        message_content=message_1,
        role="user",
        chat_id=test_thread_id,
        message_id=f"{test_thread_id}-user-1",
        timestamp=datetime.now(timezone.utc),
        message_index=0,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    
    # Append without Oxford comma
    message_2 = "My favorite book genres are Mystery, Biography and Fantasy."
    result_2 = await persist_facts_synchronously(
        project_id=project_id,
        message_content=message_2,
        role="user",
        chat_id=test_thread_id,
        message_id=f"{test_thread_id}-user-2",
        timestamp=datetime.now(timezone.utc),
        message_index=1,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    
    # Should parse 3 items: Mystery, Biography, Fantasy
    # Fantasy is duplicate, so 2 new items stored
    assert result_2.store_count == 2, f"Expected 2 new items, got {result_2.store_count}"
    assert result_2.duplicate_blocked is not None
    assert "fantasy" in result_2.duplicate_blocked, "Fantasy should be blocked as duplicate (normalized key: 'fantasy')"


@pytest.mark.asyncio
async def test_bulk_append_read_verification(test_db_setup, test_thread_id):
    """
    Test 5: Full E2E - write bulk, append bulk, then read list.
    
    Verifies the complete flow matches expected behavior.
    """
    project_id = test_db_setup["project_id"]
    
    # Write initial list
    message_1 = "My favorite book genres are Sci-Fi, Fantasy, and History."
    await persist_facts_synchronously(
        project_id=project_id,
        message_content=message_1,
        role="user",
        chat_id=test_thread_id,
        message_id=f"{test_thread_id}-user-1",
        timestamp=datetime.now(timezone.utc),
        message_index=0,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    
    # Append to list
    message_2 = "My favorite book genres are Mystery, Biography, and Fantasy."
    await persist_facts_synchronously(
        project_id=project_id,
        message_content=message_2,
        role="user",
        chat_id=test_thread_id,
        message_id=f"{test_thread_id}-user-2",
        timestamp=datetime.now(timezone.utc),
        message_index=1,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    
    # Read list
    conn = db.get_db_connection(test_db_setup["source_id"], project_id=project_id)
    cursor = conn.cursor()
    
    canonicalization_result = canonicalize_topic("book genres", invoke_teacher=False)
    canonical_topic = canonicalization_result.canonical_topic
    list_key = canonical_list_key(canonical_topic)
    
    cursor.execute("""
        SELECT fact_key, value_text
        FROM project_facts
        WHERE project_id = ? AND fact_key LIKE ? AND is_current = 1
        ORDER BY fact_key
    """, (project_id, f"{list_key}.%"))
    
    rows = cursor.fetchall()
    items = []
    for row in rows:
        fact_key = row[0]
        value_text = row[1] if len(row) > 1 else ""
        if "." in fact_key:
            try:
                rank_str = fact_key.rsplit(".", 1)[1]
                rank = int(rank_str)
                items.append({
                    "fact_key": fact_key,
                    "rank": rank,
                    "value_text": value_text
                })
            except (ValueError, IndexError):
                continue
    
    conn.close()
    
    # Verify final state
    assert len(items) == 5, f"Expected 5 facts, got {len(items)}"
    
    sorted_items = sorted(items, key=lambda f: f.get("rank", 0))
    values = [item.get("value_text", "") for item in sorted_items]
    
    # Verify ordering and contents (values may be normalized to lowercase)
    assert values[0].lower() == "sci-fi", f"Rank 1 should be Sci-Fi (normalized), got {values[0]}"
    assert values[1].lower() == "fantasy", f"Rank 2 should be Fantasy (normalized), got {values[1]}"
    assert values[2].lower() == "history", f"Rank 3 should be History (normalized), got {values[2]}"
    assert "mystery" in [v.lower() for v in values[3:5]], "Mystery should be at rank 4 or 5"
    assert "biography" in [v.lower() for v in values[3:5]], "Biography should be at rank 4 or 5"
    
    # Verify ranks are contiguous
    ranks = [item.get("rank", 0) for item in sorted_items]
    assert ranks == [1, 2, 3, 4, 5], f"Expected ranks [1,2,3,4,5], got {ranks}"
    
    # Verify ranked list invariants
    is_valid, error_msg = validate_ranked_list_invariants(items, list_key)
    assert is_valid, f"Ranked list invariants violated: {error_msg}"

