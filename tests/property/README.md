# Property-Based Tests for Fact Memory System

Comprehensive stress tests for Project cross-chat Fact Memory with 100+ scenarios across multiple projects.

## Quick Start

```bash
# Run default test suite (100 scenarios, seed=42)
pytest tests/property/test_fact_memory_property.py

# Run stress mode (1000 scenarios)
pytest tests/property/test_fact_memory_property.py -m stress

# Run with custom seed (for reproducing failures)
SEED=12345 pytest tests/property/test_fact_memory_property.py

# Run with custom number of scenarios
NUM_SCENARIOS=200 pytest tests/property/test_fact_memory_property.py
```

## What It Tests

1. **Latest Wins Semantics**: Facts resolve to the most recent value within a project
2. **Citation Correctness**: Citations always reference the correct `source_message_uuid`
3. **Cross-Project Isolation**: Zero bleed-over between projects
4. **Out-of-Order Events**: Handles messages indexed out of chronological order
5. **Deterministic Extraction**: Extractor stays stable across text variants
6. **Concurrency**: Tie-break rules for concurrent updates

## Test Structure

- **100+ Scenarios**: Each scenario creates a timeline of 3-8 messages across 2-5 chats
- **8 Projects**: Tests run across 8 different projects to verify isolation
- **20+ Statement Templates**: Tests various ways facts can be stated
- **15 Fact Keys**: Tests different types of facts (colors, addresses, emails, etc.)

## Failure Reporting

When a test fails, you'll see:
- Seed value (for reproducibility)
- Project ID and fact key
- Full message timeline with UUIDs
- Expected vs actual values
- Facts table dump for debugging

## CI Integration

Default CI mode runs with:
- Fixed seed: 42
- 100 scenarios
- Fast execution (<30-60s)

Set `STRESS_MODE=1` for heavy testing (1000 scenarios).

