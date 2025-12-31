# Facts Acceptance Tests

## Overview

The Facts acceptance tests (`server/tests/test_facts_acceptance_e2e.py`) validate end-to-end behavior of the Facts system by testing the full pipeline: `chat_with_smart_search` → routing → persistence → retrieval.

These tests use the **same code paths as the UI**, ensuring that what works in tests will work in production.

## Running Locally

### Prerequisites

- Python 3.8+
- pytest
- pytest-asyncio
- All dependencies from `server/requirements.txt`

### Run All Acceptance Tests

```bash
cd server
pytest tests/test_facts_acceptance_e2e.py -v
```

### Run Specific Test

```bash
pytest tests/test_facts_acceptance_e2e.py::test_acceptance_a_seed_ranked_list -v
```

### Run with Diagnostics

```bash
pytest tests/test_facts_acceptance_e2e.py -v -s  # -s shows print statements
```

## Test Scenarios

### A. Seed Ranked List (Bulk)
- **Input**: "My favorite vacation destinations are Japan, Italy, and New Zealand."
- **Assertions**:
  - List = [japan, italy, new zealand] ranks 1..3
  - Facts-S(3) response
  - Ordinal read: "What is my second favorite vacation destination?" => italy

### B. Bulk Append-Many (Non-Oxford + Oxford)
- **Setup**: Seed list with Japan, Italy, New Zealand
- **Step 1**: "My favorite vacation destinations are Spain, Greece and Thailand." (non-Oxford)
  - Assert append, not overwrite; ranks 1..6 contiguous
- **Step 2**: "My favorite vacation destinations are Portugal, Greece, and Japan." (Oxford)
  - Assert only Portugal added; duplicates skipped with "already at #k" message

### C. Single Unranked Duplicate
- **Setup**: Seed list with Japan, Italy, New Zealand
- **Input**: "My favorite vacation destination is Italy."
- **Assertions**:
  - NO write occurred (list unchanged)
  - Response indicates already at #2
  - Facts-S(0) response

### D. Ranked MOVE
- **Setup**: Seed list with 7 destinations
- **Input**: "My #2 favorite vacation destination is Thailand."
- **Assertions**:
  - Thailand moved to rank 2
  - Ranks remain contiguous 1..7
  - Ordinal read: "What is my second favorite vacation destination?" => thailand

### E. Ranked INSERT
- **Setup**: Seed list with 5 destinations
- **Input**: "My #3 favorite vacation destination is Iceland."
- **Assertions**:
  - Iceland inserted at rank 3
  - Items at ranks 3+ shifted down
  - Ranks contiguous 1..6

### F. Rank Beyond Length (APPEND)
- **Setup**: Seed list with 3 destinations
- **Input**: "My #99 favorite vacation destination is Morocco."
- **Assertions**:
  - Morocco appended as #4 (not #99)
  - Ranks contiguous 1..4

### G. Out-of-Range Read
- **Setup**: Seed list with 3 destinations
- **Input**: "What is my 100th favorite vacation destination?"
- **Assertions**:
  - Polite "only have N favorites" response

### H. Cross-Thread Readback
- **Setup**: Write in thread 1
- **Input**: Read in thread 2 (same project, different thread)
- **Assertions**:
  - Same list retrieved across threads

## Test Architecture

### Isolation

- Each test uses isolated `project_id` and `thread_id` (via fixtures)
- Each test uses isolated SQLite database (via `test_db_setup` fixture)
- Memory store is mocked to return empty history

### Mocking

- **Nano Router**: Mocked to return deterministic `RoutingPlan` objects
- **Memory Store**: Mocked to return empty history (prevents disk I/O)
- **LLM Calls**: Avoided by using safety net for bulk preferences (deterministic)

### Assertions

Each test asserts:

1. **Response Metadata**:
   - Facts-S/U/R counts
   - Facts-F flag (should be False)
   - Model label

2. **DB State**:
   - Ranked list invariants (uniqueness, contiguous ranks)
   - Expected values at expected ranks
   - List length matches expectations

3. **Response Content**:
   - Contains expected values (for reads)
   - Contains duplicate messages (for duplicates)
   - Contains out-of-range messages (for invalid ranks)

## Diagnostics

On test failure, diagnostics are printed showing:

- Last assistant response content
- Facts actions metadata
- Ranked list state (rank, value, is_current)
- Project ID and topic

Example:
```
=== DIAGNOSTICS: test_acceptance_a_seed_ranked_list ===
Project ID: abc123...
Topic: vacation destinations

Last Assistant Response:
  Content: Your favorite vacation destinations are...
  Facts Actions: {'S': 3, 'U': 0, 'R': 0, 'F': False}
  Model Label: GPT-5 Nano → Canonicalizer → Facts-S(3)

Ranked List State:
  Rank 1: japan
  Rank 2: italy
  Rank 3: new zealand
==================================================
```

## CI Integration

These tests run automatically in GitHub Actions on every push/PR.

See `.github/workflows/tests.yml` for configuration.

## Facts Read Intent Rules

### "Top N" vs Singleton Rank

The system distinguishes between **slice requests** ("top N") and **singleton rank requests** ("#N" or "Nth"):

- **"Top N" or "Top <word-number>"** (e.g., "top 3", "top three"):
  - Interpreted as a **SLICE** request for ranks 1..N
  - Returns a list of the first N items
  - Example: "What are my top 3 favorite activities?" → returns ranks 1, 2, 3 as a list

- **"#N" or "Nth"** (e.g., "#3", "third", "3rd"):
  - Interpreted as a **SINGLETON** request for rank N only
  - Returns a single item at rank N
  - Example: "What is my #3 favorite activity?" → returns only rank 3

**Priority**: "Top N" patterns take precedence over ordinal detection to avoid misinterpreting "top three" as rank 3 singleton.

### Out-of-Range Facts Reads (No GPT Fallback)

When the router selects Facts read (`content_plane="facts"`, `operation="read"`), the system **MUST** return a deterministic Facts response, even if:
- The query returns no results (empty list)
- The requested rank is out of range (e.g., #99 when only 8 items exist)
- Query planning fails

**Policy**: If Facts-R executes successfully (no exception), return a deterministic response explaining the condition. **Never** fall through to Index-P → GPT-5 for empty-but-valid Facts reads.

**Fallback is ONLY allowed for**:
- Parsing failures (router couldn't determine intent)
- Canonicalization failures that prevent forming a Facts read
- Database errors (connection failures, etc.)
- Explicit user requests requiring open-ended reasoning beyond Facts

**Response Format**:
- Out-of-range: "I only have N favorites stored, so there's no #X favorite."
- Empty list: "I don't have that stored yet."
- Response meta includes `facts_empty_valid=True` flag to indicate valid Facts response (no fallback)

## Warning Policy

The acceptance tests filter known sqlite3 datetime adapter deprecation warnings (Python 3.12+). These warnings are:
- **Type**: `DeprecationWarning`
- **Message**: "The default datetime adapter is deprecated as of Python 3.12"
- **Source**: `memory_service/memory_dashboard/db.py` and `server/services/facts_apply.py`

These warnings are filtered in `pytest.ini` and monitored via a guardrail in `conftest.py` that will alert if any new warning categories appear.

**Policy**: Only the specific sqlite3 datetime adapter deprecation warnings are filtered. Any other warnings will be visible and should be investigated.

## Troubleshooting

### Test Fails with "memory_store not found"

Ensure `mock_memory_store` fixture is applied (it's `autouse=True`, so it should be automatic).

### Test Fails with "Nano router not mocked"

Ensure `route_with_nano` is patched in the test. All acceptance tests should patch it.

### Test Fails with "No facts found"

Check:
1. Safety net is triggering (for bulk preferences)
2. Routing plan is correctly mocked
3. Topic canonicalization is working
4. DB is properly initialized

### Test Fails with "Invariant violation"

This indicates a real bug in the Facts system. Check:
1. Ranked list has contiguous ranks (1..N)
2. No duplicate values (normalized)
3. Only one `is_current=1` fact per rank

## Adding New Tests

1. Follow the pattern of existing tests
2. Mock `route_with_nano` to return appropriate `RoutingPlan`
3. Call `chat_with_smart_search` with test message
4. Assert response metadata and DB state
5. Add diagnostics on failure

Example:
```python
@pytest.mark.asyncio
async def test_acceptance_new_scenario(test_db_setup, test_thread_id):
    project_id = test_db_setup["project_id"]
    
    mock_plan = _create_mock_routing_plan(
        content_plane="facts",
        operation="write",
        facts_write_candidate=FactsWriteCandidate(...)
    )
    
    with patch('server.services.nano_router.route_with_nano', new_callable=AsyncMock) as mock_router:
        mock_router.return_value = mock_plan
        
        response = await chat_with_smart_search(...)
        
        # Assertions
        assert response.get("meta", {}).get("facts_actions", {}).get("S", 0) > 0
        items = _assert_ranked_list_invariants(project_id, "topic", expected_count=N)
```

