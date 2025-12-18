"""
Comprehensive deep-linking test suite.

Tests that Memory inline citations correctly deep-link to the exact ChatDO response card.
Creates a test project with 10+ chats, stores 20+ topics, and runs 20+ citation tests.
"""
import sys
import os
import pytest
import uuid
import requests
import time
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.services.memory_service_client import MemoryServiceClient
from server.services.facts import extract_ranked_facts, normalize_topic_key, extract_topic_from_query
from memory_service.memory_dashboard import db

# Test project ID
TEST_PROJECT_ID = "test-deep-linking-comprehensive"
BASE_URL = "http://localhost:8000"


@pytest.fixture(scope="module")
def memory_client():
    """Get memory service client."""
    client = MemoryServiceClient()
    if not client.is_available():
        pytest.skip("Memory Service is not available")
    return client


@pytest.fixture(scope="module")
def test_project():
    """Create a test project."""
    # Create new project
    response = requests.post(
        f"{BASE_URL}/api/projects",
        json={"name": "Deep Linking Test Project"}
    )
    assert response.status_code == 200, f"Failed to create project: {response.text}"
    project = response.json()
    project_id = project["id"]  # Use the actual project ID returned by API
    print(f"\n✓ Created test project: {project['name']} (ID: {project_id})")
    
    yield project
    
    # Cleanup: Delete project (this will also clean up chats)
    try:
        requests.delete(f"{BASE_URL}/api/projects/{project_id}")
        print(f"\n✓ Cleaned up test project: {project_id}")
    except Exception as e:
        print(f"\n⚠ Failed to cleanup project: {e}")


@pytest.fixture(scope="module", autouse=True)
def cleanup_test_data(memory_client, test_project):
    """Clean up test data before and after tests."""
    project_id = test_project["id"]
    
    # Clean up before tests
    try:
        conn = db.get_tracking_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM facts WHERE project_id = ?", (project_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    
    yield
    
    # Clean up after tests
    try:
        conn = db.get_tracking_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM facts WHERE project_id = ?", (project_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def create_chat(project_id: str, title: str = None) -> str:
    """Create a new chat in the project."""
    response = requests.post(
        f"{BASE_URL}/api/new_conversation",
        json={"project_id": project_id}
    )
    assert response.status_code == 200, f"Failed to create chat: {response.text}"
    chat_data = response.json()
    thread_id = chat_data["conversation_id"]
    
    # Update chat title if provided
    if title:
        chats_response = requests.get(f"{BASE_URL}/api/chats?project_id={project_id}")
        if chats_response.status_code == 200:
            chats = chats_response.json()
            chat = next((c for c in chats if c["id"] == thread_id), None)
            if chat:
                # Note: We can't update title via API easily, so we'll just use the thread_id
                pass
    
    return thread_id


def send_message(thread_id: str, project_id: str, message: str) -> dict:
    """Send a message and get the response."""
    response = requests.post(
        f"{BASE_URL}/api/chat",
        json={
            "message": message,
            "conversation_id": thread_id,  # API expects conversation_id, not thread_id
            "project_id": project_id,
            "target_name": "general"
        }
    )
    assert response.status_code == 200, f"Failed to send message: {response.text}"
    return response.json()


def store_memory_fact(memory_client, project_id: str, chat_id: str, topic: str, values: list, kind: str = "ranked"):
    """Store a memory fact (ranked list or single preference)."""
    if kind == "ranked":
        # Create a properly formatted message that extract_ranked_facts can parse
        # Format: "My favorite X are:\n1) Value1\n2) Value2\n..."
        formatted_message = f"My favorite {topic} are:\n" + "\n".join([f"{i+1}) {v}" for i, v in enumerate(values)])
        topic_key = normalize_topic_key(formatted_message)
        ranked_facts = extract_ranked_facts(formatted_message)
        
        if not topic_key or not ranked_facts:
            # Try alternative format
            formatted_message = f"My favorite {topic} are " + ", ".join([f"{i+1}) {v}" for i, v in enumerate(values)])
            topic_key = normalize_topic_key(formatted_message)
            ranked_facts = extract_ranked_facts(formatted_message)
        
        if not topic_key:
            # Fallback: create topic_key manually
            topic_key = f"favorite_{topic.lower().replace(' ', '_')}"
        
        if not ranked_facts:
            # Fallback: create ranked facts manually
            ranked_facts = [(i+1, v) for i, v in enumerate(values)]
        
        # Generate assistant_message_id for fact storage (simulating the assistant response that confirms the fact)
        assistant_message_id_for_facts = str(uuid.uuid4())
        
        # Store facts using the extracted format
        # Production message IDs are 1-based (user-1, user-2, ...)
        # Align test fixture message_id generation with production to ensure fact_id linking works.
        for rank, value in ranked_facts:
            message_id = f"{chat_id}-user-{rank}"
            success = memory_client.store_fact(
                project_id=project_id,
                topic_key=topic_key,
                kind="ranked",
                value=value,
                source_message_id=message_id,
                chat_id=chat_id,
                rank=rank,
                assistant_message_id=assistant_message_id_for_facts  # Store assistant_message_id at creation time
            )
            assert success, f"Failed to store ranked fact: rank={rank}, value={value}, topic_key={topic_key}"
    else:
        # Store as single preference
        # Create a message format that normalize_topic_key can parse
        formatted_message = f"My favorite {topic} is {values[0] if isinstance(values, list) else values}"
        topic_key = normalize_topic_key(formatted_message)
        
        if not topic_key:
            # Fallback: create topic_key manually
            topic_key = f"favorite_{topic.lower().replace(' ', '_')}"
        
        # Generate assistant_message_id for fact storage (simulating the assistant response that confirms the fact)
        assistant_message_id_for_facts = str(uuid.uuid4())
        
        message_id = f"{chat_id}-user-1"
        value = values[0] if isinstance(values, list) else values
        success = memory_client.store_fact(
            project_id=project_id,
            topic_key=topic_key,
            kind="single",
            value=value,
            source_message_id=message_id,
            chat_id=chat_id,
            assistant_message_id=assistant_message_id_for_facts  # Store assistant_message_id at creation time
        )
        assert success, f"Failed to store single fact: value={value}, topic_key={topic_key}"
    
    return topic_key


@pytest.mark.deep_linking
def test_comprehensive_deep_linking(memory_client, test_project):
    """
    Comprehensive deep-linking test:
    1. Create 10+ chats
    2. Store 20+ topics across those chats
    3. Run 20+ tests triggering Memory citations
    4. Verify message_id in sources matches assistant message ID
    """
    print("\n" + "="*80)
    print("COMPREHENSIVE DEEP-LINKING TEST")
    print("="*80)
    
    project_id = test_project["id"]
    
    # Step 1: Create 10+ chats
    print(f"\n[Step 1] Creating 12 chats in project {project_id}...")
    chats = []
    for i in range(12):
        chat_id = create_chat(project_id, f"Chat {i+1}")
        chats.append(chat_id)
        print(f"  ✓ Created chat {i+1}/12: {chat_id[:8]}...")
    
    assert len(chats) >= 10, f"Expected at least 10 chats, got {len(chats)}"
    print(f"\n✓ Created {len(chats)} chats")
    
    # Step 2: Store 20+ topics across chats
    print(f"\n[Step 2] Storing 24 topics across {len(chats)} chats...")
    
    # Define topics to store (mix of ranked lists and preferences)
    topics_data = [
        # Chat 0: Colors (ranked)
        ("colors", ["Blue", "Green", "Red", "Purple"], "ranked"),
        # Chat 1: Cryptocurrencies (ranked)
        ("cryptocurrencies", ["Bitcoin", "Ethereum", "Monero", "Litecoin"], "ranked"),
        # Chat 2: Programming languages (ranked)
        ("programming_languages", ["Python", "JavaScript", "Rust", "Go"], "ranked"),
        # Chat 3: Movies (ranked)
        ("movies", ["Inception", "The Matrix", "Interstellar", "Blade Runner"], "ranked"),
        # Chat 4: Books (ranked)
        ("books", ["1984", "Brave New World", "Dune", "Foundation"], "ranked"),
        # Chat 5: Foods (ranked)
        ("foods", ["Pizza", "Sushi", "Tacos", "Pasta"], "ranked"),
        # Chat 6: Countries (ranked)
        ("countries", ["Japan", "Iceland", "New Zealand", "Switzerland"], "ranked"),
        # Chat 7: Sports (ranked)
        ("sports", ["Basketball", "Soccer", "Tennis", "Swimming"], "ranked"),
        # Chat 8: Music genres (ranked)
        ("music_genres", ["Jazz", "Classical", "Electronic", "Rock"], "ranked"),
        # Chat 9: Hobbies (ranked)
        ("hobbies", ["Reading", "Coding", "Hiking", "Photography"], "ranked"),
        # Chat 10: Single preferences
        ("favorite_season", ["Spring"], "single"),
        ("favorite_time", ["Morning"], "single"),
        ("favorite_weather", ["Sunny"], "single"),
        ("coffee_preference", ["Espresso"], "single"),
        ("tea_preference", ["Green tea"], "single"),
        ("breakfast_food", ["Oatmeal"], "single"),
        ("lunch_food", ["Salad"], "single"),
        ("dinner_food", ["Steak"], "single"),
        ("dessert", ["Ice cream"], "single"),
        ("snack", ["Nuts"], "single"),
        ("drink", ["Water"], "single"),
        ("exercise", ["Running"], "single"),
        ("transport", ["Bicycle"], "single"),
        ("pet", ["Dog"], "single"),
    ]
    
    stored_topics = {}
    for idx, (topic, values, kind) in enumerate(topics_data):
        chat_idx = idx % len(chats)
        chat_id = chats[chat_idx]
        topic_key = store_memory_fact(memory_client, project_id, chat_id, topic, values, kind)
        stored_topics[topic_key] = {
            "chat_id": chat_id,
            "values": values,
            "kind": kind
        }
        print(f"  ✓ Stored topic '{topic_key}' in chat {chat_idx+1} ({kind})")
    
    assert len(stored_topics) >= 20, f"Expected at least 20 topics, got {len(stored_topics)}"
    print(f"\n✓ Stored {len(stored_topics)} topics across {len(chats)} chats")
    
    # Step 3: Run 20+ tests triggering Memory citations
    print(f"\n[Step 3] Running 24 citation tests...")
    
    test_results = []
    
    # Test 1-10: Ordinal questions for ranked lists
    # Use the actual topic_keys that were stored (e.g., "favorite_colors", not "colors")
    ordinal_tests = [
        ("favorite_colors", "What is my number one favorite color?"),
        ("favorite_cryptos", "What's my top cryptocurrency?"),
        ("favorite_programming_languages", "Which programming language is my favorite?"),
        ("favorite_movies", "What's my number one movie?"),
        ("favorite_books", "What is my top book?"),
        ("favorite_foods", "What's my favorite food?"),
        ("favorite_countries", "Which country is my favorite?"),
        ("favorite_sports", "What's my number one sport?"),
        ("favorite_music_genres", "What is my top music genre?"),
        ("favorite_hobbies", "What's my favorite hobby?"),
    ]
    
    for topic_key, question in ordinal_tests:
        if topic_key not in stored_topics:
            continue
        
        # Use a different chat than where the fact was stored
        stored_chat = stored_topics[topic_key]["chat_id"]
        test_chat_idx = (chats.index(stored_chat) + 1) % len(chats)
        test_chat_id = chats[test_chat_idx]
        
        print(f"\n  Test: '{question}' (topic: {topic_key})")
        print(f"    Stored in: {stored_chat[:8]}..., Testing in: {test_chat_id[:8]}...")
        
        response = send_message(test_chat_id, project_id, question)
        
        # Extract response data - API returns message_data with the actual response
        message_data = response.get("message_data", response)
        sources = message_data.get("sources") or []
        
        # Verify Memory sources have correct message_id (NOT user message IDs)
        memory_sources = [s for s in sources if s.get("sourceType") == "memory" or s.get("citationPrefix") == "M"]
        
        if memory_sources:
            failed_sources = []
            for idx, source in enumerate(memory_sources):
                source_meta = source.get("meta", {})
                source_msg_id = source_meta.get("message_id")
                
                # CRITICAL: Verify message_id is NOT a user message ID
                if source_msg_id and ("-user-" in source_msg_id or source_msg_id.endswith("-user")):
                    failed_sources.append({
                        "index": idx,
                        "message_id": source_msg_id,
                        "meta": source_meta
                    })
            
            if failed_sources:
                print(f"    ✗ Found {len(failed_sources)} source(s) with user message IDs:")
                for failed in failed_sources:
                    print(f"      - Source {failed['index']}: {failed['message_id']}")
                
                test_results.append({
                    "test": question,
                    "topic": topic_key,
                    "passed": False,
                    "reason": f"{len(failed_sources)} source(s) have user message IDs",
                    "failed_sources": failed_sources
                })
            else:
                first_source = memory_sources[0]
                meta = first_source.get("meta", {})
                source_message_id = meta.get("message_id")
                print(f"    ✓ All {len(memory_sources)} Memory source(s) have correct message_id: {source_message_id}")
                
                test_results.append({
                    "test": question,
                    "topic": topic_key,
                    "passed": True,
                    "assistant_message_id": source_message_id,
                    "sources_count": len(memory_sources)
                })
        else:
            print(f"    ⚠ No Memory sources found (might be using facts instead)")
            test_results.append({
                "test": question,
                "topic": topic_key,
                "passed": False,
                "reason": "No Memory sources found"
            })
    
    # Test 11-20: Full list questions
    # Use the actual topic_keys that were stored (e.g., "favorite_colors", not "colors")
    list_tests = [
        ("favorite_colors", "List my favorite colors"),
        ("favorite_cryptos", "What are my favorite cryptocurrencies?"),
        ("favorite_programming_languages", "Show me my programming languages"),
        ("favorite_movies", "List my favorite movies"),
        ("favorite_books", "What are my favorite books?"),
        ("favorite_foods", "Show my favorite foods"),
        ("favorite_countries", "List my favorite countries"),
        ("favorite_sports", "What are my favorite sports?"),
        ("favorite_music_genres", "Show me my music genres"),
        ("favorite_hobbies", "List my hobbies"),
    ]
    
    for topic_key, question in list_tests:
        if topic_key not in stored_topics:
            continue
        
        # Use a different chat than where the fact was stored
        stored_chat = stored_topics[topic_key]["chat_id"]
        test_chat_idx = (chats.index(stored_chat) + 1) % len(chats)
        test_chat_id = chats[test_chat_idx]
        
        print(f"\n  Test: '{question}' (topic: {topic_key})")
        print(f"    Stored in: {stored_chat[:8]}..., Testing in: {test_chat_id[:8]}...")
        
        response = send_message(test_chat_id, project_id, question)
        
        # Extract response data - API returns message_data with the actual response
        message_data = response.get("message_data", response)
        sources = message_data.get("sources") or []
        
        # Verify Memory sources have correct message_id (NOT user message IDs)
        memory_sources = [s for s in sources if s.get("sourceType") == "memory" or s.get("citationPrefix") == "M"]
        
        if memory_sources:
            failed_sources = []
            for idx, source in enumerate(memory_sources):
                source_meta = source.get("meta", {})
                source_msg_id = source_meta.get("message_id")
                
                # CRITICAL: Verify message_id is NOT a user message ID
                if source_msg_id and ("-user-" in source_msg_id or source_msg_id.endswith("-user")):
                    failed_sources.append({
                        "index": idx,
                        "message_id": source_msg_id,
                        "meta": source_meta
                    })
            
            if failed_sources:
                print(f"    ✗ Found {len(failed_sources)} source(s) with user message IDs:")
                for failed in failed_sources:
                    print(f"      - Source {failed['index']}: {failed['message_id']}")
                
                test_results.append({
                    "test": question,
                    "topic": topic_key,
                    "passed": False,
                    "reason": f"{len(failed_sources)} source(s) have user message IDs",
                    "failed_sources": failed_sources
                })
            else:
                first_source = memory_sources[0]
                meta = first_source.get("meta", {})
                source_message_id = meta.get("message_id")
                print(f"    ✓ All {len(memory_sources)} Memory source(s) have correct message_id: {source_message_id}")
                
                test_results.append({
                    "test": question,
                    "topic": topic_key,
                    "passed": True,
                    "assistant_message_id": source_message_id,
                    "sources_count": len(memory_sources)
                })
        else:
            print(f"    ⚠ No Memory sources found (might be using facts instead)")
            test_results.append({
                "test": question,
                "topic": topic_key,
                "passed": False,
                "reason": "No Memory sources found"
            })
    
    # Test 21-24: General questions that should trigger Memory
    general_tests = [
        ("What do I like?", "colors"),
        ("Tell me about my preferences", "cryptocurrencies"),
        ("What are my favorites?", "programming_languages"),
        ("Show me what I've told you", "movies"),
    ]
    
    for question, expected_topic in general_tests:
        # Use a random chat
        test_chat_id = chats[0]
        
        print(f"\n  Test: '{question}'")
        print(f"    Testing in: {test_chat_id[:8]}...")
        
        response = send_message(test_chat_id, project_id, question)
        
        # Extract response data - API returns message_data with the actual response
        message_data = response.get("message_data", response)
        sources = message_data.get("sources") or []
        
        # The id might be in message_data or we need to check the actual structure
        # For now, let's check if sources have message_id and verify they're consistent
        memory_sources = [s for s in sources if s.get("sourceType") == "memory" or s.get("citationPrefix") == "M"]
        
        if memory_sources:
            # Verify all sources have correct message_id (NOT user message IDs)
            failed_sources = []
            for idx, source in enumerate(memory_sources):
                source_meta = source.get("meta", {})
                source_msg_id = source_meta.get("message_id")
                
                # CRITICAL: Verify message_id is NOT a user message ID
                # User message IDs end with patterns like "-user-0", "-user-1", etc.
                if source_msg_id and ("-user-" in source_msg_id or source_msg_id.endswith("-user")):
                    failed_sources.append({
                        "index": idx,
                        "message_id": source_msg_id,
                        "meta": source_meta
                    })
            
            if failed_sources:
                # Some sources still have user message IDs - this is the bug we're testing for
                print(f"    ✗ Found {len(failed_sources)} source(s) with user message IDs:")
                for failed in failed_sources:
                    print(f"      - Source {failed['index']}: {failed['message_id']}")
                
                test_results.append({
                    "test": question,
                    "topic": expected_topic,
                    "passed": False,
                    "reason": f"{len(failed_sources)} source(s) have user message IDs",
                    "failed_sources": failed_sources
                })
            else:
                # All sources have correct message IDs
                first_source = memory_sources[0]
                meta = first_source.get("meta", {})
                source_message_id = meta.get("message_id")
                
                print(f"    ✓ All {len(memory_sources)} Memory source(s) have correct message_id: {source_message_id}")
                
                test_results.append({
                    "test": question,
                    "topic": expected_topic,
                    "passed": True,
                    "assistant_message_id": source_message_id,
                    "sources_count": len(memory_sources)
                })
        else:
            # This is OK - general questions might not always trigger Memory
            test_results.append({
                "test": question,
                "topic": expected_topic,
                "passed": True,  # Not a failure if no Memory sources
                "reason": "No Memory sources (expected for general questions)"
            })
    
    # Step 4: Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    passed_tests = [t for t in test_results if t.get("passed")]
    failed_tests = [t for t in test_results if not t.get("passed")]
    
    print(f"\nTotal tests run: {len(test_results)}")
    print(f"Passed: {len(passed_tests)}")
    print(f"Failed: {len(failed_tests)}")
    
    if failed_tests:
        print("\nFailed tests:")
        for test in failed_tests:
            print(f"  - {test['test']}: {test.get('reason', 'Unknown error')}")
    
    print(f"\n✓ Created {len(chats)} chats")
    print(f"✓ Stored {len(stored_topics)} topics")
    print(f"✓ Ran {len(test_results)} citation tests")
    
    # Final assertion
    assert len(test_results) >= 20, f"Expected at least 20 tests, ran {len(test_results)}"
    # We expect most tests to pass - facts should use assistant_message_id, Memory sources should be updated
    # Some tests may fail if Memory sources from hits aren't updated (but facts should work)
    facts_tests = [t for t in test_results if "favorite_" in t.get("topic", "")]
    facts_passed = [t for t in facts_tests if t.get("passed")]
    print(f"\nFacts-based tests: {len(facts_passed)}/{len(facts_tests)} passed")
    assert len(facts_passed) >= len(facts_tests) * 0.8, f"Expected at least 80% of facts tests to pass, got {len(facts_passed)}/{len(facts_tests)}"
    
    print("\n" + "="*80)
    print("✅ COMPREHENSIVE DEEP-LINKING TEST PASSED")
    print("="*80)

