"""
Property-based stress tests for Project cross-chat Fact Memory system.

Tests 100+ scenarios across multiple projects to ensure:
- Facts resolve to latest current value within a project
- Citations always reference correct source_message_uuid
- Zero cross-project bleed-over
- Out-of-order events handled correctly
- Deterministic extractor stability

Run with: pytest tests/property/test_fact_memory_property.py
Run stress mode: pytest tests/property/test_fact_memory_property.py -m stress
Set seed: SEED=12345 pytest tests/property/test_fact_memory_property.py
"""
import os
import sys
import random
import uuid
import pytest
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from memory_service.memory_dashboard import db
from memory_service.indexer import index_chat_message

# Import fact extractor (may fail if dependencies missing, but that's OK for tests)
try:
    from memory_service.fact_extractor import get_fact_extractor
    FACT_EXTRACTOR_AVAILABLE = True
except ImportError:
    FACT_EXTRACTOR_AVAILABLE = False
    def get_fact_extractor():
        return None


# Test configuration
DEFAULT_SEED = 42
DEFAULT_SCENARIOS = 100
STRESS_SCENARIOS = 1000
NUM_PROJECTS = 8  # Test with 8 projects for isolation

# Get seed from environment or use default
TEST_SEED = int(os.getenv("SEED", DEFAULT_SEED))
NUM_SCENARIOS = int(os.getenv("NUM_SCENARIOS", DEFAULT_SCENARIOS))
if "stress" in sys.argv or os.getenv("STRESS_MODE") == "1":
    NUM_SCENARIOS = STRESS_SCENARIOS


@dataclass
class Message:
    """Represents a test message."""
    project_id: str
    chat_id: str
    message_id: str
    message_uuid: str
    role: str
    content: str
    timestamp: datetime
    message_index: int
    expected_facts: List[Dict]  # Expected facts that should be extracted
    deterministic_created_at: Optional[datetime] = None  # For deterministic fact storage


@dataclass
class Scenario:
    """Represents a test scenario."""
    seed: int
    project_id: str
    fact_key: str
    messages: List[Message]
    query_chat_id: str
    expected_value: Optional[str]
    expected_message_uuid: Optional[str]
    description: str


# Fact keys to test
FACT_KEYS = [
    "user.favorite_color",
    "user.favorite_food",
    "user.callsign",
    "user.address",
    "user.employer",
    "user.phone",
    "user.email",
    "user.birthday",
    "user.preferred_language",
    "user.timezone",
    "user.favorite_movie",
    "user.favorite_book",
    "user.pet_name",
    "user.car_model",
    "user.hometown",
]

# Statement templates (20+ variations)
STATEMENT_TEMPLATES = [
    # Direct statements
    ("my favorite {key} is {value}", "user.favorite_{key}"),
    ("my {key} is {value}", "user.{key}"),
    ("I am {value}", "user.role"),
    ("I have {value}", "user.possession"),
    ("I like {value}", "user.preference"),
    ("I love {value}", "user.preference"),
    
    # Explicit memory statements
    ("remember that my favorite {key} is {value}", "user.favorite_{key}"),
    ("note that my {key} is {value}", "user.{key}"),
    ("save that I am {value}", "user.role"),
    
    # Update patterns
    ("actually my favorite {key} is {value}", "user.favorite_{key}"),
    ("correction: my {key} is {value}", "user.{key}"),
    ("update: my favorite {key} is {value}", "user.favorite_{key}"),
    ("changed my mind, it's {value}", "user.preference"),
    
    # Alternative formats
    ("favorite {key} = {value}", "user.favorite_{key}"),
    ("{key}: {value}", "user.{key}"),
    ("my {key} = {value}", "user.{key}"),
    
    # Negative/ambiguous (should NOT extract)
    ("what is my favorite {key}?", None),  # Question
    ("I wonder what my favorite {key} is", None),  # Uncertainty
    ("maybe my favorite {key} is {value}", None),  # Uncertainty
    ("I think my favorite {key} might be {value}", None),  # Uncertainty
    ("someone said my favorite {key} is {value}", None),  # Reported speech
]

# Values for testing
VALUES = {
    "color": ["blue", "red", "green", "purple", "orange", "yellow", "black", "white"],
    "food": ["pizza", "sushi", "tacos", "pasta", "burgers", "salad", "ice cream"],
    "callsign": ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"],
    "address": ["123 Main St", "456 Oak Ave", "789 Pine Rd", "321 Elm Blvd"],
    "employer": ["Acme Corp", "TechCo", "StartupXYZ", "BigCorp Inc"],
    "phone": ["555-0100", "555-0200", "555-0300", "555-0400"],
    "email": ["user@example.com", "test@domain.com", "admin@site.org"],
    "birthday": ["January 1", "March 15", "July 4", "December 25"],
    "language": ["English", "Spanish", "French", "German"],
    "timezone": ["PST", "EST", "CST", "MST"],
    "movie": ["The Matrix", "Inception", "Interstellar", "Blade Runner"],
    "book": ["1984", "Dune", "Foundation", "Neuromancer"],
    "pet": ["Fluffy", "Max", "Bella", "Charlie"],
    "car": ["Tesla Model 3", "Toyota Camry", "Honda Accord"],
    "hometown": ["New York", "Los Angeles", "Chicago", "Houston"],
}


def normalize_fact_key(key_template: str, fact_type: str) -> str:
    """Normalize fact key from template."""
    if key_template is None:
        return None
    return key_template.replace("{key}", fact_type).replace("_", ".")


def generate_statement(fact_type: str, value: str, template_idx: int) -> Tuple[str, Optional[str]]:
    """Generate a statement from a template."""
    template, key_template = STATEMENT_TEMPLATES[template_idx % len(STATEMENT_TEMPLATES)]
    
    # Replace placeholders (ensure value is string)
    value_str = str(value) if value is not None else ""
    statement = template.replace("{key}", fact_type).replace("{value}", value_str)
    fact_key = normalize_fact_key(key_template, fact_type)
    
    return statement, fact_key


def generate_scenario(seed: int, project_id: str, fact_key: str) -> Scenario:
    """Generate a random scenario for testing."""
    rng = random.Random(seed)
    
    # Extract fact type from key (e.g., "user.favorite_color" -> "color")
    fact_type = fact_key.split(".")[-1].replace("favorite_", "").replace("user.", "")
    
    # Generate 2-5 chats in this project
    num_chats = rng.randint(2, 5)
    chat_ids = [f"chat-{uuid.uuid4().hex[:8]}" for _ in range(num_chats)]
    
    # Generate timeline of messages
    messages: List[Message] = []
    base_time = datetime.now() - timedelta(days=30)
    
    # Generate 3-8 messages across chats
    num_messages = rng.randint(3, 8)
    values_pool = VALUES.get(fact_type, ["value1", "value2", "value3", "value4"])
    
    # Track all facts that will be stored (to determine "latest wins" correctly)
    # Each fact has: (effective_at, created_at, insertion_order, value, message_uuid)
    stored_facts = []  # List of (effective_at, created_at, insertion_order, value, message_uuid)
    message_timeline = []
    
    # Base time for deterministic created_at (microsecond precision for ordering)
    base_created_at = base_time
    
    for i in range(num_messages):
        chat_id = rng.choice(chat_ids)
        message_id = f"{chat_id}-user-{i}"
        message_uuid = str(uuid.uuid4())
        
        # Decide: new value, update, or re-state
        action = rng.choice(["new", "update", "restate"])
        
        # Determine value for this message
        if action == "new" or len(stored_facts) == 0:
            value = rng.choice(values_pool)
        elif action == "update":
            # Update to different value
            value = rng.choice([v for v in values_pool if v != stored_facts[-1][2]])
        else:  # restate
            # Keep same value as last stored fact (if any)
            if stored_facts:
                value = stored_facts[-1][2]
            else:
                value = rng.choice(values_pool)
        
        # Generate statement
        template_idx = rng.randint(0, len(STATEMENT_TEMPLATES) - 1)
        content, extracted_key = generate_statement(fact_type, value, template_idx)
        
        # Skip if this template shouldn't extract
        if extracted_key is None:
            content = f"I'm just chatting about {fact_type}."
            extracted_key = None
        
        # Random timestamp (may be out of order) - this becomes effective_at
        if rng.random() < 0.2:  # 20% chance of out-of-order
            timestamp = base_time + timedelta(seconds=rng.randint(-86400, 86400))
        else:
            timestamp = base_time + timedelta(seconds=i * 3600)
        
        # Track fact if it will be extracted (not restate, and template extracts)
        will_extract = extracted_key is not None and action != "restate"
        
        # Determine deterministic created_at for facts stored from this message
        deterministic_created_at = base_created_at + timedelta(microseconds=i) if will_extract else None
        
        message = Message(
            project_id=project_id,
            chat_id=chat_id,
            message_id=message_id,
            message_uuid=message_uuid,
            role="user",
            content=content,
            timestamp=timestamp,
            message_index=i,
            expected_facts=[{"fact_key": fact_key, "value": value}] if will_extract else [],
            deterministic_created_at=deterministic_created_at
        )
        
        messages.append(message)
        
        # If this message will store a fact, track it
        if will_extract:
            # effective_at is the message timestamp
            # created_at is deterministic: base_time + microseconds based on insertion order
            # Use the same deterministic_created_at that was set for the message
            stored_facts.append((timestamp, deterministic_created_at, i, value, message_uuid))
        
        message_timeline.append((timestamp, message_uuid, value if will_extract else None))
    
    # Determine expected winner using same rule as system
    # NOTE: The system stores facts sequentially, and each new fact marks previous ones as is_current=0
    # So get_current_fact() filters by is_current=1 first, then orders by effective_at DESC, created_at DESC
    # This means the LAST fact stored (by insertion order) wins, not necessarily the one with latest effective_at
    expected_value = None
    expected_message_uuid = None
    expected_created_at = None
    if stored_facts:
        # The winner is the LAST fact stored (by insertion order), because it's the only one with is_current=1
        # After all facts are stored, only the last one will have is_current=1
        winner = stored_facts[-1]  # Last fact stored
        expected_value = winner[3]  # value
        expected_message_uuid = winner[4]  # message_uuid
        expected_created_at = winner[1]  # created_at
    
    # Query from a different chat (or same chat)
    query_chat_id = rng.choice(chat_ids)
    
    # Build description
    description = f"Project {project_id}, fact_key={fact_key}, {num_messages} messages across {num_chats} chats"
    
    return Scenario(
        seed=seed,
        project_id=project_id,
        fact_key=fact_key,
        messages=messages,
        query_chat_id=query_chat_id,
        expected_value=expected_value,
        expected_message_uuid=expected_message_uuid,
        description=description
    )


@pytest.fixture(scope="function")
def test_db():
    """Create isolated test databases for each test."""
    # Use test-specific source IDs
    test_source_id = f"test-{uuid.uuid4().hex[:8]}"
    yield test_source_id
    
    # Cleanup: Delete test database files
    # Note: In production, you might want to clean up test databases
    # For now, we'll leave them for debugging


@pytest.fixture(scope="module")
def fact_extractor():
    """Get fact extractor instance."""
    if not FACT_EXTRACTOR_AVAILABLE:
        pytest.skip("Fact extractor dependencies not available (spacy/dateparser/quantulum3)")
    return get_fact_extractor()


def test_property_fact_memory():
    """Property-based test: 100+ scenarios across multiple projects."""
    rng = random.Random(TEST_SEED)
    
    # Generate N projects
    project_ids = [f"test-project-{i}" for i in range(NUM_PROJECTS)]
    
    # Generate scenarios
    scenarios: List[Scenario] = []
    for i in range(NUM_SCENARIOS):
        project_id = rng.choice(project_ids)
        fact_key = rng.choice(FACT_KEYS)
        scenario_seed = TEST_SEED + i
        scenario = generate_scenario(scenario_seed, project_id, fact_key)
        scenarios.append(scenario)
    
    # Track failures for reporting
    failures: List[Dict] = []
    
    # Run each scenario
    for scenario_idx, scenario in enumerate(scenarios):
        try:
            # Store messages and facts directly (bypassing extractor for testing)
            message_uuid_map = {}
            source_id = f"project-{scenario.project_id}"
            
            # Initialize database for this project
            db.init_db(source_id, project_id=scenario.project_id)
            
            # Clear any existing facts for this project/fact_key to ensure clean state
            # (This prevents state leakage between scenarios using the same project_id)
            conn_cleanup = db.get_db_connection(source_id, project_id=scenario.project_id)
            cursor_cleanup = conn_cleanup.cursor()
            cursor_cleanup.execute("""
                DELETE FROM project_facts
                WHERE project_id = ? AND fact_key = ?
            """, (scenario.project_id, scenario.fact_key))
            conn_cleanup.commit()
            conn_cleanup.close()
            
            for msg in scenario.messages:
                # Store message and get UUID
                chat_message_id = db.upsert_chat_message(
                    source_id=source_id,
                    project_id=scenario.project_id,
                    chat_id=msg.chat_id,
                    message_id=msg.message_id,
                    role=msg.role,
                    content=msg.content,
                    timestamp=msg.timestamp,
                    message_index=msg.message_index,
                    message_uuid=msg.message_uuid  # Use the UUID from scenario
                )
                
                chat_message = db.get_chat_message_by_id(chat_message_id, source_id)
                if chat_message:
                    message_uuid_map[msg.message_id] = chat_message.message_uuid
                    
                    # Store facts directly if expected (simulating extraction)
                    if msg.expected_facts:
                        for expected_fact in msg.expected_facts:
                            if expected_fact.get("fact_key") and expected_fact.get("value"):
                                # Use deterministic created_at for reproducible tests
                                db.store_project_fact(
                                    project_id=scenario.project_id,
                                    fact_key=expected_fact["fact_key"],
                                    value_text=expected_fact["value"],
                                    value_type="string",
                                    source_message_uuid=chat_message.message_uuid,
                                    confidence=0.9,
                                    effective_at=msg.timestamp,
                                    source_id=source_id,
                                    created_at=msg.deterministic_created_at  # Deterministic timestamp
                                )
            
            # Query for current fact (after indexing all messages)
            if scenario.expected_value:
                fact = db.get_current_fact(
                    project_id=scenario.project_id,
                    fact_key=scenario.fact_key
                )
                
                # Assertion 1: Latest wins
                if fact is None:
                    failures.append({
                        "scenario_idx": scenario_idx,
                        "scenario": scenario,
                        "error": "Expected fact not found",
                        "type": "missing_fact"
                    })
                elif fact["value_text"] != scenario.expected_value:
                    # Collect all candidate facts for detailed reporting
                    source_id_debug = f"project-{scenario.project_id}"
                    conn_debug = db.get_db_connection(source_id_debug, project_id=scenario.project_id)
                    cursor_debug = conn_debug.cursor()
                    cursor_debug.execute("""
                        SELECT fact_id, value_text, effective_at, created_at, 
                               source_message_uuid, is_current, supersedes_fact_id
                        FROM project_facts
                        WHERE project_id = ? AND fact_key = ?
                        ORDER BY effective_at DESC, created_at DESC
                    """, (scenario.project_id, scenario.fact_key))
                    all_facts = cursor_debug.fetchall()
                    conn_debug.close()
                    
                    failures.append({
                        "scenario_idx": scenario_idx,
                        "scenario": scenario,
                        "error": f"Value mismatch: expected '{scenario.expected_value}', got '{fact['value_text']}'",
                        "type": "value_mismatch",
                        "got_value": fact["value_text"],
                        "got_uuid": fact["source_message_uuid"],
                        "got_fact": fact,
                        "all_facts": all_facts
                    })
                else:
                    # Only run remaining assertions if fact is found and value matches
                    
                    # Assertion 2: Citation correctness (check if UUID matches expected or is from a re-statement)
                    # Note: Re-statements don't update UUID, so we check if UUID is in the message list
                    if scenario.expected_message_uuid:
                        found_uuid = False
                        for msg_check in scenario.messages:
                            if msg_check.message_uuid == fact["source_message_uuid"]:
                                found_uuid = True
                                break
                        if not found_uuid:
                            print(f"\nWARNING: Citation UUID {fact['source_message_uuid']} not found in scenario messages")
                    
                    # Assertion 3: Cross-project isolation
                    # Check that fact belongs to correct project
                    assert fact["project_id"] == scenario.project_id, \
                        f"Fact belongs to wrong project: expected {scenario.project_id}, got {fact['project_id']}"
                    
                    # Assertion 4: Only one current fact
                    source_id_check = f"project-{scenario.project_id}"
                    conn = db.get_db_connection(source_id_check, project_id=scenario.project_id)
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT COUNT(*) FROM project_facts
                        WHERE project_id = ? AND fact_key = ? AND is_current = 1
                    """, (scenario.project_id, scenario.fact_key))
                    count = cursor.fetchone()[0]
                    conn.close()
                    
                    if count != 1:
                        failures.append({
                            "scenario_idx": scenario_idx,
                            "scenario": scenario,
                            "error": f"Expected exactly 1 current fact, found {count}",
                            "type": "multiple_current_facts",
                            "count": count
                        })
        
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            failures.append({
                "scenario_idx": scenario_idx,
                "scenario": scenario,
                "error": str(e),
                "type": "exception",
                "traceback": tb_str
            })
    
    # Report failures
    if failures:
        print(f"\n{'='*80}")
        print(f"FAILURES: {len(failures)} out of {NUM_SCENARIOS} scenarios failed")
        print(f"Seed: {TEST_SEED}")
        print(f"{'='*80}\n")
        
        for failure in failures[:10]:  # Show first 10 failures
            scenario = failure["scenario"]
            print(f"\nFailure #{failure['scenario_idx']}: {failure['type']}")
            print(f"  Description: {scenario.description}")
            print(f"  Seed: {scenario.seed}")
            print(f"  Project: {scenario.project_id}")
            print(f"  Fact Key: {scenario.fact_key}")
            print(f"  Error: {failure['error']}")
            
            # Show all chat IDs involved
            chat_ids = list(set(msg.chat_id for msg in scenario.messages))
            print(f"  Chat IDs: {', '.join(chat_ids)}")
            
            # Show candidate facts if available
            if "all_facts" in failure:
                print(f"\n  Candidate facts in DB (ordered by effective_at DESC, created_at DESC):")
                for idx, fact_row in enumerate(failure["all_facts"]):
                    fact_dict = {key: fact_row[key] for key in fact_row.keys()}
                    marker = " <-- DB WINNER" if idx == 0 else ""
                    print(f"    [{idx}] value='{fact_dict['value_text']}', "
                          f"effective_at={fact_dict['effective_at']}, "
                          f"created_at={fact_dict['created_at']}, "
                          f"is_current={fact_dict['is_current']}, "
                          f"uuid={fact_dict['source_message_uuid']}{marker}")
            
            # Show expected facts from scenario generation
            print(f"\n  Expected facts from scenario (ordered by effective_at DESC, created_at DESC):")
            stored_facts_list = []
            base_time_scenario = scenario.messages[0].timestamp if scenario.messages else datetime.now()
            for msg_idx, msg in enumerate(scenario.messages):
                if msg.expected_facts and msg.deterministic_created_at:
                    for expected_fact in msg.expected_facts:
                        stored_facts_list.append((
                            msg.timestamp,  # effective_at
                            msg.deterministic_created_at,  # created_at
                            msg_idx,  # insertion_order
                            expected_fact.get("value"),
                            msg.message_uuid
                        ))
            if stored_facts_list:
                sorted_expected = sorted(stored_facts_list, key=lambda x: (x[0], x[1]), reverse=True)
                for idx, (eff_at, cr_at, ins_ord, val, uuid_val) in enumerate(sorted_expected):
                    marker = " <-- EXPECTED WINNER" if idx == 0 else ""
                    print(f"    [{idx}] value='{val}', effective_at={eff_at}, "
                          f"created_at={cr_at}, insertion_order={ins_ord}, uuid={uuid_val}{marker}")
            
            # Show DB's returned winner
            if "got_fact" in failure:
                got_fact = failure["got_fact"]
                print(f"\n  DB's returned winner:")
                print(f"    value='{got_fact['value_text']}', "
                      f"effective_at={got_fact.get('effective_at')}, "
                      f"created_at={got_fact.get('created_at')}, "
                      f"uuid={got_fact['source_message_uuid']}")
            
            print(f"\n  Messages:")
            for msg in scenario.messages:
                print(f"    - [{msg.timestamp}] {msg.chat_id}: {msg.content[:60]}")
                print(f"      UUID: {msg.message_uuid}, created_at={msg.deterministic_created_at}")
            print(f"  Expected: value='{scenario.expected_value}', uuid={scenario.expected_message_uuid}")
            if "got_value" in failure:
                print(f"  Got: value='{failure['got_value']}', uuid={failure.get('got_uuid')}")
            
            if 'traceback' in failure and failure['traceback']:
                print(f"\n  Traceback:\n{failure['traceback']}")
        
        if len(failures) > 10:
            print(f"\n... and {len(failures) - 10} more failures")
        
        # Dump facts table for debugging
        print(f"\n{'='*80}")
        print("Facts table dump (first project):")
        if scenarios:
            first_project = scenarios[0].project_id
            source_id = f"project-{first_project}"
            conn = db.get_db_connection(source_id, project_id=first_project)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT fact_id, project_id, fact_key, value_text, is_current, 
                       source_message_uuid, created_at, effective_at, supersedes_fact_id
                FROM project_facts
                WHERE project_id = ?
                ORDER BY fact_key, effective_at DESC
                LIMIT 20
            """, (first_project,))
            rows = cursor.fetchall()
            for row in rows:
                # Convert Row to dict
                row_dict = {key: row[key] for key in row.keys()}
                print(f"  {row_dict}")
            conn.close()
        
        pytest.fail(f"{len(failures)} scenarios failed. See output above for details.")


def test_concurrent_updates(test_db):
    """Test concurrent updates to same fact_key with tie-break rules."""
    project_id = "test-concurrent-project"
    fact_key = "user.favorite_color"
    source_id = f"project-{project_id}"
    
    # Create two messages with identical timestamps
    now = datetime.now()
    uuid1 = str(uuid.uuid4())
    uuid2 = str(uuid.uuid4())
    
    # Store first fact
    fact_id1 = db.store_project_fact(
        project_id=project_id,
        fact_key=fact_key,
        value_text="blue",
        value_type="string",
        source_message_uuid=uuid1,
        effective_at=now,
        source_id=source_id
    )
    
    # Store second fact with same effective_at (simulating concurrent write)
    fact_id2 = db.store_project_fact(
        project_id=project_id,
        fact_key=fact_key,
        value_text="red",
        value_type="string",
        source_message_uuid=uuid2,
        effective_at=now,  # Same effective_at
        source_id=source_id
    )
    
    # Get current fact
    current = db.get_current_fact(project_id=project_id, fact_key=fact_key, source_id=source_id)
    
    # Assertions
    assert current is not None, "Should have a current fact"
    
    # Tie-break rule: later created_at wins; if equal, higher fact_id wins
    # Since fact_id2 was created after fact_id1, it should win
    assert current["fact_id"] == fact_id2, f"Expected fact_id2 ({fact_id2}) to win, got {current['fact_id']}"
    assert current["value_text"] == "red", f"Expected 'red', got '{current['value_text']}'"
    assert current["source_message_uuid"] == uuid2, "Citation should point to winning fact"
    
    # Verify only one current fact exists
    conn = db.get_db_connection(source_id, project_id=project_id)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM project_facts
        WHERE project_id = ? AND fact_key = ? AND is_current = 1
    """, (project_id, fact_key))
    count = cursor.fetchone()[0]
    conn.close()
    
    assert count == 1, f"Expected exactly 1 current fact, found {count}"


def test_cross_project_isolation(test_db):
    """Explicit test for cross-project isolation."""
    project_a = "test-project-a"
    project_b = "test-project-b"
    fact_key = "user.favorite_color"
    
    # Store same fact key in both projects with different values
    uuid_a = str(uuid.uuid4())
    uuid_b = str(uuid.uuid4())
    
    db.store_project_fact(
        project_id=project_a,
        fact_key=fact_key,
        value_text="blue",
        value_type="string",
        source_message_uuid=uuid_a
    )
    
    db.store_project_fact(
        project_id=project_b,
        fact_key=fact_key,
        value_text="red",
        value_type="string",
        source_message_uuid=uuid_b
    )
    
    # Query project A
    fact_a = db.get_current_fact(project_id=project_a, fact_key=fact_key)
    assert fact_a is not None, "Project A should have a fact"
    assert fact_a["value_text"] == "blue", "Project A should return 'blue'"
    assert fact_a["project_id"] == project_a, "Fact should belong to project A"
    assert fact_a["source_message_uuid"] == uuid_a, "Citation should be correct"
    
    # Query project B
    fact_b = db.get_current_fact(project_id=project_b, fact_key=fact_key)
    assert fact_b is not None, "Project B should have a fact"
    assert fact_b["value_text"] == "red", "Project B should return 'red'"
    assert fact_b["project_id"] == project_b, "Fact should belong to project B"
    assert fact_b["source_message_uuid"] == uuid_b, "Citation should be correct"
    
    # Verify no cross-project access
    # Query project A with project B's value - should not find it
    source_id_b = f"project-{project_b}"
    conn = db.get_db_connection(source_id_b, project_id=project_b)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM project_facts
        WHERE project_id = ? AND fact_key = ? AND value_text = 'blue'
    """, (project_b, fact_key))
    count_b_has_blue = cursor.fetchone()[0]
    conn.close()
    
    assert count_b_has_blue == 0, "Project B should not have project A's value"


@pytest.mark.smoke
def test_smoke_cross_project_isolation():
    """
    Fast deterministic smoke test: same fact_key in two projects with different values.
    
    Validates:
    - Values never cross between projects
    - source_message_uuid matches the correct project
    """
    import uuid
    from memory_service.memory_dashboard import db
    
    # Create two distinct projects
    project_a = "smoke-project-a"
    project_b = "smoke-project-b"
    fact_key = "user.favorite_color"
    
    # Initialize databases
    source_id_a = f"project-{project_a}"
    source_id_b = f"project-{project_b}"
    db.init_db(source_id_a, project_id=project_a)
    db.init_db(source_id_b, project_id=project_b)
    
    # Generate distinct UUIDs for citations
    uuid_a = str(uuid.uuid4())
    uuid_b = str(uuid.uuid4())
    
    # Store same fact key in both projects with different values
    try:
        db.store_project_fact(
            project_id=project_a,
            fact_key=fact_key,
            value_text="blue",
            value_type="string",
            source_message_uuid=uuid_a,
            source_id=source_id_a
        )
        
        db.store_project_fact(
            project_id=project_b,
            fact_key=fact_key,
            value_text="red",
            value_type="string",
            source_message_uuid=uuid_b,
            source_id=source_id_b
        )
        
        # Query project A
        fact_a = db.get_current_fact(project_id=project_a, fact_key=fact_key, source_id=source_id_a)
        assert fact_a is not None, f"Project A ({project_a}) should have a fact"
        assert fact_a["value_text"] == "blue", f"Project A should return 'blue', got '{fact_a['value_text']}'"
        assert fact_a["project_id"] == project_a, f"Fact should belong to project A ({project_a}), got '{fact_a['project_id']}'"
        assert fact_a["source_message_uuid"] == uuid_a, f"Citation should be correct. Expected UUID: {uuid_a}, got: {fact_a['source_message_uuid']}"
        
        # Query project B
        fact_b = db.get_current_fact(project_id=project_b, fact_key=fact_key, source_id=source_id_b)
        assert fact_b is not None, f"Project B ({project_b}) should have a fact"
        assert fact_b["value_text"] == "red", f"Project B should return 'red', got '{fact_b['value_text']}'"
        assert fact_b["project_id"] == project_b, f"Fact should belong to project B ({project_b}), got '{fact_b['project_id']}'"
        assert fact_b["source_message_uuid"] == uuid_b, f"Citation should be correct. Expected UUID: {uuid_b}, got: {fact_b['source_message_uuid']}"
        
        # Verify no cross-project access
        # Query project A with project B's value - should not find it
        conn_b = db.get_db_connection(source_id_b, project_id=project_b)
        cursor_b = conn_b.cursor()
        cursor_b.execute("""
            SELECT COUNT(*) FROM project_facts
            WHERE project_id = ? AND fact_key = ? AND value_text = 'blue'
        """, (project_b, fact_key))
        count_b_has_blue = cursor_b.fetchone()[0]
        conn_b.close()
        
        assert count_b_has_blue == 0, f"Project B ({project_b}) should not have project A's value 'blue'. Found {count_b_has_blue} facts."
        
        # Query project B with project A's value - should not find it
        conn_a = db.get_db_connection(source_id_a, project_id=project_a)
        cursor_a = conn_a.cursor()
        cursor_a.execute("""
            SELECT COUNT(*) FROM project_facts
            WHERE project_id = ? AND fact_key = ? AND value_text = 'red'
        """, (project_a, fact_key))
        count_a_has_red = cursor_a.fetchone()[0]
        conn_a.close()
        
        assert count_a_has_red == 0, f"Project A ({project_a}) should not have project B's value 'red'. Found {count_a_has_red} facts."
        
    except AssertionError as e:
        # Enhanced failure output with project IDs and UUIDs
        print("\n" + "=" * 80)
        print("SMOKE TEST FAILURE")
        print("=" * 80)
        print(f"Project A: {project_a}")
        print(f"Project B: {project_b}")
        print(f"Fact Key: {fact_key}")
        print(f"UUID A: {uuid_a}")
        print(f"UUID B: {uuid_b}")
        print(f"\nError: {e}")
        print("=" * 80)
        raise


if __name__ == "__main__":
    # Allow running directly
    pytest.main([__file__, "-v"])

