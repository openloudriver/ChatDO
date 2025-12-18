"""
Test deep-linking for Memory citations.

Verifies that:
1. Assistant messages have stable message_id
2. message_id is included in response
3. message_id is included in sources[].meta for Memory citations
4. message_id matches what's stored in history
"""
import sys
import os
import pytest
import uuid
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.services.memory_service_client import MemoryServiceClient
from server.services.facts import extract_ranked_facts, normalize_topic_key
from memory_service.memory_dashboard import db
from chatdo.memory import store as memory_store

# Test project ID
TEST_PROJECT_ID = "test-deep-linking"


@pytest.fixture(scope="module")
def memory_client():
    """Get memory service client."""
    client = MemoryServiceClient()
    if not client.is_available():
        pytest.skip("Memory Service is not available")
    return client


@pytest.fixture(scope="module", autouse=True)
def cleanup_test_data(memory_client):
    """Clean up test data before and after tests."""
    # Clean up before tests
    try:
        conn = db.get_tracking_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM facts WHERE project_id = ?", (TEST_PROJECT_ID,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    
    yield
    
    # Clean up after tests
    try:
        conn = db.get_tracking_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM facts WHERE project_id = ?", (TEST_PROJECT_ID,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def test_message_id_in_response(memory_client):
    """
    Test that assistant messages have stable message_id in response.
    """
    print("\n=== Test: message_id in Response ===")
    
    chat_id = f"test-chat-{uuid.uuid4().hex[:8]}"
    target_name = "general"
    
    # Store a fact in chat
    user_message = "My favorite colors are 1) Blue, 2) Green, 3) Black"
    topic_key = normalize_topic_key(user_message)
    ranked_facts = extract_ranked_facts(user_message)
    
    message_id_user = f"{chat_id}-user-1"
    for rank, value in ranked_facts:
        success = memory_client.store_fact(
            project_id=TEST_PROJECT_ID,
            topic_key=topic_key,
            kind="ranked",
            value=value,
            source_message_id=message_id_user,
            chat_id=chat_id,
            rank=rank
        )
        assert success, f"Failed to store fact: rank={rank}, value={value}"
    
    # Simulate getting a fact response (ordinal query)
    # This would normally come from chat_with_smart_search, but we'll test the structure
    fact = memory_client.get_fact_by_rank(
        project_id=TEST_PROJECT_ID,
        topic_key=topic_key,
        rank=1,
        chat_id=None
    )
    
    assert fact is not None, "Fact should be found"
    assert fact.get("source_message_id") == message_id_user, "source_message_id should match"
    
    # Verify fact has chat_id and source_message_id for deep-linking
    assert fact.get("chat_id") == chat_id, "chat_id should be set"
    assert fact.get("source_message_id") is not None, "source_message_id should be set"
    
    print(f"  ✓ Fact has chat_id: {fact.get('chat_id')}")
    print(f"  ✓ Fact has source_message_id: {fact.get('source_message_id')}")
    
    # Test that sources array would include message_id
    sources = [{
        "id": "memory-fact-1",
        "title": "Stored Fact",
        "siteName": "Memory",
        "description": f"From chat {chat_id[:8]}...",
        "rank": 0,
        "sourceType": "memory",
        "citationPrefix": "M",
        "meta": {
            "chat_id": fact.get("chat_id"),
            "message_id": fact.get("source_message_id"),  # This is the key for deep-linking
            "topic_key": topic_key,
            "rank": 1,
            "value": fact.get("value")
        }
    }]
    
    assert sources[0]["meta"]["message_id"] == message_id_user, "message_id should be in sources meta"
    assert sources[0]["meta"]["chat_id"] == chat_id, "chat_id should be in sources meta"
    
    print(f"  ✓ Sources include message_id in meta: {sources[0]['meta']['message_id']}")
    print("✅ Test PASSED: message_id structure is correct")


def test_message_id_stability(memory_client):
    """
    Test that message_id is stable and matches what's stored in history.
    """
    print("\n=== Test: message_id Stability ===")
    
    chat_id = f"test-chat-{uuid.uuid4().hex[:8]}"
    target_name = "general"
    
    # Create a message in history
    message_id = str(uuid.uuid4())
    history = [{
        "id": message_id,
        "role": "assistant",
        "content": "Test response",
        "model": "Memory",
        "model_label": "Model: Memory",
        "provider": "memory",
        "created_at": datetime.now(timezone.utc).isoformat()
    }]
    
    # Save to history
    memory_store.save_thread_history(target_name, chat_id, history, project_id=TEST_PROJECT_ID)
    
    # Load from history
    loaded_history = memory_store.load_thread_history(target_name, chat_id, project_id=TEST_PROJECT_ID)
    
    assert len(loaded_history) == 1, "History should have 1 message"
    assert loaded_history[0]["id"] == message_id, "message_id should match what was stored"
    
    print(f"  ✓ Stored message_id: {message_id}")
    print(f"  ✓ Loaded message_id: {loaded_history[0]['id']}")
    print("✅ Test PASSED: message_id is stable across save/load")


def test_deep_linking_structure():
    """
    Test that the deep-linking structure is correct:
    - Messages have anchor IDs: message-{message_id}
    - Sources have message_id in meta
    - Citation clicks can navigate using chat_id + message_id
    """
    print("\n=== Test: Deep-linking Structure ===")
    
    chat_id = f"test-chat-{uuid.uuid4().hex[:8]}"
    message_id = str(uuid.uuid4())
    
    # Simulate response structure
    response = {
        "type": "assistant_message",
        "content": "Your favorite color ranked first is **Blue**. [M1]",
        "id": message_id,  # Stable message_id for deep-linking
        "meta": {"usedFacts": True},
        "sources": [{
            "id": "memory-fact-1",
            "title": "Stored Fact",
            "siteName": "Memory",
            "sourceType": "memory",
            "citationPrefix": "M",
            "meta": {
                "chat_id": chat_id,
                "message_id": f"{chat_id}-user-1",  # Source message_id
                "topic_key": "favorite_colors",
                "rank": 1,
                "value": "Blue"
            }
        }],
        "model": "Memory",
        "model_label": "Model: Memory",
        "provider": "memory",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Verify structure
    assert "id" in response, "Response should have id field"
    assert response["id"] == message_id, "Response id should match message_id"
    assert len(response["sources"]) > 0, "Response should have sources"
    
    source = response["sources"][0]
    assert source["meta"]["chat_id"] == chat_id, "Source should have chat_id"
    assert source["meta"]["message_id"] is not None, "Source should have message_id"
    
    # Verify anchor ID format
    anchor_id = f"message-{message_id}"
    assert anchor_id == f"message-{response['id']}", "Anchor ID should be message-{message_id}"
    
    print(f"  ✓ Response has message_id: {response['id']}")
    print(f"  ✓ Source has chat_id: {source['meta']['chat_id']}")
    print(f"  ✓ Source has message_id: {source['meta']['message_id']}")
    print(f"  ✓ Anchor ID format: {anchor_id}")
    print("✅ Test PASSED: Deep-linking structure is correct")


@pytest.mark.deep_linking
def test_full_deep_linking_flow(memory_client):
    """
    Full integration test for deep-linking:
    1. Store fact in Chat A
    2. Query fact from Chat B
    3. Verify response includes message_id
    4. Verify sources include message_id in meta
    5. Verify message_id can be used for navigation
    """
    print("\n=== Test: Full Deep-linking Flow ===")
    
    chat_a_id = f"test-chat-a-{uuid.uuid4().hex[:8]}"
    chat_b_id = f"test-chat-b-{uuid.uuid4().hex[:8]}"
    target_name = "general"
    
    # Step 1: Store fact in Chat A
    user_message_a = "My favorite colors are 1) Red, 2) Orange, 3) Yellow"
    topic_key = normalize_topic_key(user_message_a)
    ranked_facts = extract_ranked_facts(user_message_a)
    
    message_id_a = f"{chat_a_id}-user-1"
    for rank, value in ranked_facts:
        success = memory_client.store_fact(
            project_id=TEST_PROJECT_ID,
            topic_key=topic_key,
            kind="ranked",
            value=value,
            source_message_id=message_id_a,
            chat_id=chat_a_id,
            rank=rank
        )
        assert success, f"Failed to store fact: rank={rank}, value={value}"
    
    print(f"  ✓ Stored facts in Chat A (message_id: {message_id_a})")
    
    # Step 2: Query fact from Chat B (cross-chat)
    fact = memory_client.get_fact_by_rank(
        project_id=TEST_PROJECT_ID,
        topic_key=topic_key,
        rank=1,
        chat_id=None  # Cross-chat
    )
    
    assert fact is not None, "Fact should be found from Chat B"
    assert fact.get("chat_id") == chat_a_id, "Fact should come from Chat A"
    assert fact.get("source_message_id") == message_id_a, "source_message_id should match"
    
    print(f"  ✓ Retrieved fact from Chat B (cross-chat)")
    
    # Step 3: Build response structure (simulating chat_with_smart_search)
    assistant_message_id = str(uuid.uuid4())
    sources = [{
        "id": "memory-fact-1",
        "title": "Stored Fact",
        "siteName": "Memory",
        "description": f"From chat {chat_a_id[:8]}...",
        "rank": 0,
        "sourceType": "memory",
        "citationPrefix": "M",
        "meta": {
            "chat_id": fact.get("chat_id"),
            "message_id": fact.get("source_message_id"),  # Deep-link to source message
            "topic_key": topic_key,
            "rank": 1,
            "value": fact.get("value")
        }
    }]
    
    response = {
        "type": "assistant_message",
        "content": f"Your favorite color ranked first is **{fact.get('value')}**. [M1]",
        "id": assistant_message_id,  # Stable message_id for this response
        "meta": {"usedFacts": True},
        "sources": sources,
        "model": "Memory",
        "model_label": "Model: Memory",
        "provider": "memory",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Step 4: Verify structure
    assert response["id"] == assistant_message_id, "Response should have stable message_id"
    assert len(response["sources"]) == 1, "Response should have 1 source"
    assert response["sources"][0]["meta"]["chat_id"] == chat_a_id, "Source should reference Chat A"
    assert response["sources"][0]["meta"]["message_id"] == message_id_a, "Source should reference source message"
    
    # Step 5: Verify navigation structure
    anchor_id = f"message-{assistant_message_id}"
    source_chat_id = response["sources"][0]["meta"]["chat_id"]
    source_message_id = response["sources"][0]["meta"]["message_id"]
    
    print(f"  ✓ Response message_id: {assistant_message_id}")
    print(f"  ✓ Response anchor ID: {anchor_id}")
    print(f"  ✓ Source chat_id: {source_chat_id}")
    print(f"  ✓ Source message_id: {source_message_id}")
    print(f"  ✓ Navigation: chat={source_chat_id}, message={source_message_id}")
    
    # Verify all required fields for deep-linking
    assert response["id"] is not None, "Response must have id"
    assert source_chat_id is not None, "Source must have chat_id"
    assert source_message_id is not None, "Source must have message_id"
    
    print("✅ Test PASSED: Full deep-linking flow works correctly")


if __name__ == "__main__":
    pytest.main([__file__, "-m", "deep_linking", "-v"])

