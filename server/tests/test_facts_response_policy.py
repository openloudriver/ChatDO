"""
Regression tests for Facts response policy.

Ensures duplicate-only bulk writes NEVER return Facts-F and always return
appropriate "already at #k" messages.

All tests are self-contained and require no external configuration.
Run with: pytest -q
"""
import pytest
import re
from datetime import datetime, timezone
from server.services.facts_persistence import persist_facts_synchronously
from server.services.facts_retrieval import execute_facts_plan
from server.contracts.facts_ops import FactsQueryPlan
from server.services.facts_apply import validate_ranked_list_invariants
from server.services.facts_normalize import canonical_list_key
from server.services.canonicalizer import canonicalize_topic
from memory_service.memory_dashboard import db


@pytest.mark.asyncio
async def test_duplicate_only_bulk_write_no_facts_f(test_db_setup, test_thread_id):
    """
    TEST 1: Duplicate-only bulk write must NOT return Facts-F.
    
    This test prevents the regression where valid bulk preference writes
    return "I couldn't extract any facts from that message."
    
    Scenario:
    - Seed ranked list: "My favorite book genres are Sci-Fi, Fantasy, History."
    - Then submit: "My favorite book genres are Fantasy, History."
    - Expected: Returns duplicate confirmation, NOT Facts-F
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Step 1: Seed initial ranked list
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
    
    # Verify initial list was created
    assert result_1.store_count == 3, "Initial list should have 3 items"
    assert result_1.duplicate_blocked is None or len(result_1.duplicate_blocked) == 0
    
    # Step 2: Submit duplicate-only bulk write
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
    
    # CRITICAL ASSERTIONS: Must NOT return Facts-F
    assert result_2.store_count == 0, "No new items should be stored (all duplicates)"
    assert result_2.update_count == 0, "No updates expected"
    assert result_2.duplicate_blocked is not None, "Duplicates should be blocked"
    assert len(result_2.duplicate_blocked) == 2, f"Expected 2 duplicates, got {len(result_2.duplicate_blocked)}"
    
    # Verify safety net was used (for bulk preference statement)
    # This ensures we're hitting the real pipeline, not a bypass
    assert result_2.safety_net_used is True, \
        "Safety net should be used for bulk preference statement 'My favorite book genres are Fantasy, History.'"
    
    # Verify duplicate info contains rank positions
    # duplicate_blocked uses normalized (lowercase) keys
    assert "fantasy" in result_2.duplicate_blocked, "Fantasy should be in duplicate_blocked (normalized key)"
    assert "history" in result_2.duplicate_blocked, "History should be in duplicate_blocked (normalized key)"
    
    fantasy_info = result_2.duplicate_blocked["fantasy"]
    history_info = result_2.duplicate_blocked["history"]
    
    assert fantasy_info["existing_rank"] == 2, f"Fantasy should be at rank 2, got {fantasy_info['existing_rank']}"
    assert history_info["existing_rank"] == 3, f"History should be at rank 3, got {history_info['existing_rank']}"
    
    # Verify DB state unchanged (still Sci-Fi, Fantasy, History in same ranks)
    conn = db.get_db_connection(source_id, project_id=project_id)
    cursor = conn.cursor()
    
    canonicalization_result = canonicalize_topic("book genres", invoke_teacher=False)
    canonical_topic = canonicalization_result.canonical_topic
    list_key = canonical_list_key(canonical_topic)
    
    # Query ranked list items directly
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
    
    assert len(items) == 3, f"DB should still have 3 items, got {len(items)}"
    
    # Verify ranks are still 1, 2, 3
    ranks = [item["rank"] for item in items]
    assert sorted(ranks) == [1, 2, 3], f"Expected ranks [1,2,3], got {sorted(ranks)}"
    
    # Verify values are correct (values may be normalized to lowercase)
    values = {item["rank"]: item["value_text"] for item in items}
    assert values[1].lower() == "sci-fi", f"Rank 1 should be Sci-Fi (normalized), got {values[1]}"
    assert values[2].lower() == "fantasy", f"Rank 2 should be Fantasy (normalized), got {values[2]}"
    assert values[3].lower() == "history", f"Rank 3 should be History (normalized), got {values[3]}"
    
    # Verify ranked list invariants
    is_valid, error_msg = validate_ranked_list_invariants(items, list_key)
    assert is_valid, f"Ranked list invariants violated: {error_msg}"


@pytest.mark.asyncio
async def test_oxford_comma_parsing_e2e(test_db_setup, test_thread_id):
    """
    TEST 2: Oxford comma parsing works end-to-end.
    
    Verifies that "Spain, Greece, and Thailand" parses correctly
    and doesn't produce "and Thailand" artifacts.
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Step 1: Seed initial list
    message_1 = "My favorite vacation destinations are Japan, Italy, Iceland."
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
    
    assert result_1.store_count == 3, "Initial list should have 3 items"
    
    # Step 2: Append with Oxford comma
    message_2 = "My favorite vacation destinations are Spain, Greece, and Thailand."
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
    
    # Verify 3 new items appended
    assert result_2.store_count == 3, f"Expected 3 new items, got {result_2.store_count}"
    assert result_2.duplicate_blocked is None or len(result_2.duplicate_blocked) == 0
    
    # Verify safety net was used (for bulk preference statement with Oxford comma)
    assert result_2.safety_net_used is True, \
        "Safety net should be used for bulk preference statement with Oxford comma"
    
    # Verify no "and Thailand" artifact in stored values
    for fact_key in result_2.stored_fact_keys:
        fact = db.get_current_fact(project_id=project_id, fact_key=fact_key)
        if fact:
            value = fact.get("value_text", "")
            assert not value.lower().startswith("and "), f"Found 'and' artifact in value: {value}"
            assert value.lower() in ["spain", "greece", "thailand"], f"Unexpected value: {value}"
    
    # Verify final list state
    conn = db.get_db_connection(source_id, project_id=project_id)
    cursor = conn.cursor()
    
    canonicalization_result = canonicalize_topic("vacation destinations", invoke_teacher=False)
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
    
    assert len(items) == 6, f"Expected 6 items total, got {len(items)}"
    
    # Verify ranks are contiguous 1..6
    ranks = sorted([item["rank"] for item in items])
    assert ranks == [1, 2, 3, 4, 5, 6], f"Expected ranks [1,2,3,4,5,6], got {ranks}"
    
    # Verify values are correct (order: Japan, Italy, Iceland, Spain, Greece, Thailand)
    # Values may be normalized to lowercase
    values = {item["rank"]: item["value_text"] for item in items}
    assert values[1].lower() == "japan", f"Rank 1 should be Japan (normalized), got {values[1]}"
    assert values[2].lower() == "italy", f"Rank 2 should be Italy (normalized), got {values[2]}"
    assert values[3].lower() == "iceland", f"Rank 3 should be Iceland (normalized), got {values[3]}"
    assert values[4].lower() in ["spain", "greece", "thailand"], f"Rank 4 should be one of new items, got {values[4]}"
    assert values[5].lower() in ["spain", "greece", "thailand"], f"Rank 5 should be one of new items, got {values[5]}"
    assert values[6].lower() in ["spain", "greece", "thailand"], f"Rank 6 should be one of new items, got {values[6]}"
    
    # Verify all new items are present (case-insensitive)
    new_items = {v.lower() for v in [values[4], values[5], values[6]]}
    assert new_items == {"spain", "greece", "thailand"}, f"New items should be Spain, Greece, Thailand, got {new_items}"
    
    # Verify ranked list invariants
    is_valid, error_msg = validate_ranked_list_invariants(items, list_key)
    assert is_valid, f"Ranked list invariants violated: {error_msg}"


@pytest.mark.asyncio
async def test_non_oxford_comma_parsing_e2e(test_db_setup, test_thread_id):
    """
    TEST 3: Non-Oxford comma parsing works end-to-end.
    
    Verifies that "Spain, Greece and Thailand" (no Oxford comma) parses correctly.
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
    # Submit with non-Oxford comma
    message = "My favorite vacation destinations are Spain, Greece and Thailand."
    result = await persist_facts_synchronously(
        project_id=project_id,
        message_content=message,
        role="user",
        chat_id=test_thread_id,
        message_id=f"{test_thread_id}-user-1",
        timestamp=datetime.now(timezone.utc),
        message_index=0,
        write_intent_detected=True,
        routing_plan_candidate=None
    )
    
    # Verify 3 items stored
    assert result.store_count == 3, f"Expected 3 items, got {result.store_count}"
    assert result.duplicate_blocked is None or len(result.duplicate_blocked) == 0
    
    # Verify safety net was used (for bulk preference statement without Oxford comma)
    assert result.safety_net_used is True, \
        "Safety net should be used for bulk preference statement without Oxford comma"
    
    # Verify no "and Thailand" artifact
    for fact_key in result.stored_fact_keys:
        fact = db.get_current_fact(project_id=project_id, fact_key=fact_key)
        if fact:
            value = fact.get("value_text", "")
            assert not value.lower().startswith("and "), f"Found 'and' artifact in value: {value}"
            assert value.lower() in ["spain", "greece", "thailand"], f"Unexpected value: {value}"
    
    # Verify final list state
    conn = db.get_db_connection(source_id, project_id=project_id)
    cursor = conn.cursor()
    
    canonicalization_result = canonicalize_topic("vacation destinations", invoke_teacher=False)
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
    
    assert len(items) == 3, f"Expected 3 items, got {len(items)}"
    
    # Verify ranks are contiguous 1..3
    ranks = sorted([item["rank"] for item in items])
    assert ranks == [1, 2, 3], f"Expected ranks [1,2,3], got {ranks}"
    
    # Verify all values are present (case-insensitive, values may be normalized)
    values = {item["value_text"].lower() for item in items}
    assert values == {"spain", "greece", "thailand"}, f"Expected all three values, got {values}"
    
    # Verify ranked list invariants
    is_valid, error_msg = validate_ranked_list_invariants(items, list_key)
    assert is_valid, f"Ranked list invariants violated: {error_msg}"


@pytest.mark.asyncio
async def test_ranked_list_invariants_after_bulk_append(test_db_setup, test_thread_id):
    """
    TEST 4: Verify ranked list invariants are maintained after bulk append.
    
    Ensures that after any bulk append operation:
    - Ranks are contiguous (1..N, no gaps)
    - Values are unique (normalized)
    - Single rank per value
    """
    project_id = test_db_setup["project_id"]
    source_id = test_db_setup["source_id"]
    
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
    
    # Verify invariants after first write
    conn = db.get_db_connection(source_id, project_id=project_id)
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
    
    rows_1 = cursor.fetchall()
    items_1 = []
    for row in rows_1:
        fact_key = row[0]
        value_text = row[1] if len(row) > 1 else ""
        if "." in fact_key:
            try:
                rank_str = fact_key.rsplit(".", 1)[1]
                rank = int(rank_str)
                items_1.append({
                    "fact_key": fact_key,
                    "rank": rank,
                    "value_text": value_text
                })
            except (ValueError, IndexError):
                continue
    
    is_valid_1, error_msg_1 = validate_ranked_list_invariants(items_1, list_key)
    assert is_valid_1, f"Invariants violated after first write: {error_msg_1}"
    
    # Step 2: Append to list
    message_2 = "My favorite book genres are Mystery, Biography, and Fantasy."
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
    
    # Verify invariants after second write
    cursor.execute("""
        SELECT fact_key, value_text
        FROM project_facts
        WHERE project_id = ? AND fact_key LIKE ? AND is_current = 1
        ORDER BY fact_key
    """, (project_id, f"{list_key}.%"))
    
    rows_2 = cursor.fetchall()
    items_2 = []
    for row in rows_2:
        fact_key = row[0]
        value_text = row[1] if len(row) > 1 else ""
        if "." in fact_key:
            try:
                rank_str = fact_key.rsplit(".", 1)[1]
                rank = int(rank_str)
                items_2.append({
                    "fact_key": fact_key,
                    "rank": rank,
                    "value_text": value_text
                })
            except (ValueError, IndexError):
                continue
    
    conn.close()
    
    is_valid_2, error_msg_2 = validate_ranked_list_invariants(items_2, list_key)
    assert is_valid_2, f"Invariants violated after second write: {error_msg_2}"
    
    # Verify we have 5 items (3 initial + 2 new, Fantasy is duplicate)
    assert len(items_2) == 5, f"Expected 5 items, got {len(items_2)}"
    
    # Verify ranks are contiguous 1..5
    ranks = sorted([item["rank"] for item in items_2])
    assert ranks == [1, 2, 3, 4, 5], f"Expected ranks [1,2,3,4,5], got {ranks}"
    
    # Verify Fantasy appears only once (case-insensitive, values may be normalized)
    fantasy_count = sum(1 for item in items_2 if item["value_text"].lower() == "fantasy")
    assert fantasy_count == 1, f"Fantasy should appear exactly once, found {fantasy_count} times"

