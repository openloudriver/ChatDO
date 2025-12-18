# Fact Memory Property Test Suite - Implementation Summary

## Overview

Comprehensive property-based stress tests for Project cross-chat Fact Memory system with 100+ scenarios across multiple projects.

## Files Created

1. **`tests/property/test_fact_memory_property.py`** - Main test suite
2. **`tests/property/README.md`** - Usage documentation
3. **`tests/__init__.py`** - Package marker
4. **`tests/property/__init__.py`** - Package marker
5. **`pytest.ini`** - Pytest configuration

## Features Implemented

### 1. Property-Based Test Suite
- **100+ scenarios** (configurable via `NUM_SCENARIOS` env var)
- **8 projects** for isolation testing
- **Seeded randomness** for reproducibility (default seed: 42)
- **Deterministic** - same seed produces same scenarios

### 2. Scenario Generator
- **15 fact keys**: favorite_color, callsign, address, employer, phone, email, birthday, etc.
- **20+ statement templates**:
  - Direct statements: "my favorite color is X"
  - Explicit memory: "remember that my favorite color is X"
  - Updates: "actually my favorite color is X"
  - Negative cases: questions, uncertainty statements (should NOT extract)
- **3-8 messages** per scenario across **2-5 chats**
- **Update patterns**: new, update, re-state
- **Out-of-order timestamps**: 20% chance of out-of-order indexing

### 3. Assertions

#### Latest Wins
- Verifies facts resolve to the most recent value
- Handles multiple updates correctly
- Tests re-statements (idempotency)

#### Citation Correctness
- Verifies `source_message_uuid` points to correct message
- Handles re-statements (UUID doesn't change)

#### Cross-Project Isolation
- Explicit check: `fact["project_id"] == scenario.project_id`
- Tests same fact_key in multiple projects with different values
- Verifies no bleed-over

#### Single Current Fact
- Ensures only one `is_current=1` fact exists per fact_key
- Verifies "latest wins" properly marks old facts as `is_current=0`

### 4. Concurrency Test
- Tests tie-break rules for concurrent updates
- Same `effective_at` timestamp
- Verifies deterministic resolution (later `created_at` wins)

### 5. Failure Reporting
When a test fails, prints:
- Seed value (for reproducibility)
- Project ID and fact key
- Full message timeline with UUIDs
- Expected vs actual values
- Facts table dump for debugging

### 6. Performance
- Target: <30-60s for 100 scenarios
- Uses direct database calls (no network overhead)
- Fast execution for CI

## Usage

```bash
# Default: 100 scenarios, seed=42
pytest tests/property/test_fact_memory_property.py

# Stress mode: 1000 scenarios
pytest tests/property/test_fact_memory_property.py -m stress

# Custom seed (for reproducing failures)
SEED=12345 pytest tests/property/test_fact_memory_property.py

# Custom number of scenarios
NUM_SCENARIOS=200 pytest tests/property/test_fact_memory_property.py

# Run specific test
pytest tests/property/test_fact_memory_property.py::test_cross_project_isolation
```

## Test Structure

1. **`test_property_fact_memory`** - Main property-based test (100+ scenarios)
2. **`test_concurrent_updates`** - Concurrency/tie-break test
3. **`test_cross_project_isolation`** - Explicit isolation test

## Dependencies

Tests require:
- pytest
- All memory_service dependencies (spacy, dateparser, quantulum3 are optional but recommended)

If dependencies are missing, tests will skip with a clear message.

## CI Integration

Default CI mode:
- Fixed seed: 42
- 100 scenarios
- Fast execution

Set `STRESS_MODE=1` for heavy testing (1000 scenarios).

