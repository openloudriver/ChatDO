# Facts Acceptance Tests - Optimization Summary

## Performance Improvements

### Before Optimization
- **Total runtime**: ~38-51 seconds
- **Slowest test**: 10.56s (test_acceptance_a_seed_ranked_list)
- **Warnings**: 130+ (all sqlite3 datetime adapter deprecation)

### After Optimization
- **Total runtime**: ~7.72 seconds (**~80% faster**)
- **Slowest test**: 3.43s (test_acceptance_a_seed_ranked_list)
- **Warnings**: 0 (filtered)

### Test-by-Test Comparison

| Test | Before | After | Improvement |
|------|--------|-------|-------------|
| test_acceptance_a_seed_ranked_list | 10.56s | 3.43s | 67% faster |
| test_acceptance_g_out_of_range_read | 8.81s | 0.03s | 99% faster |
| test_acceptance_h_cross_thread_readback | 6.72s | 0.21s | 97% faster |
| test_acceptance_d_ranked_move | 6.55s | 0.22s | 97% faster |
| test_acceptance_b_bulk_append_many | 1.26s | 0.30s | 76% faster |
| test_acceptance_e_ranked_insert | 0.72s | 0.20s | 72% faster |
| test_acceptance_c_single_unranked_duplicate | 0.58s | 0.22s | 62% faster |
| test_acceptance_f_rank_beyond_length | 0.56s | 0.18s | 68% faster |

## Optimizations Applied

### 1. Warning Filtering (Part A)
- **Added targeted filter** in `pytest.ini` for sqlite3 datetime adapter deprecation warnings
- **Added guardrail** in `conftest.py` to detect and alert on unexpected warnings
- **Result**: Clean test output, no warning noise

### 2. Mocking Optimizations (Part B)
- **Mocked `plan_facts_query`**: Prevents LLM calls for read operations
- **Mocked canonicalizer**: Fast normalization without teacher model calls
- **Result**: Eliminated async delays from LLM/teacher model calls

### 3. Test Isolation
- **Maintained isolation**: Each test still uses isolated project_id, thread_id, and DB
- **No shared state**: Tests remain deterministic and independent

## Warning Policy

### Allowed Warnings
Only the following warning signature is filtered:
- **Type**: `DeprecationWarning`
- **Message**: "The default datetime adapter is deprecated as of Python 3.12"
- **Source files**: 
  - `memory_service/memory_dashboard/db.py`
  - `server/services/facts_apply.py`

### Guardrail
The `conftest.py` guardrail will:
- Track all warnings during test execution
- Alert if any unexpected warnings appear
- Print a summary of unexpected warnings at the end of the test run

This ensures that new warnings are immediately visible and can be addressed.

## Verification

### Test Status
- ✅ All 8 acceptance tests pass
- ✅ Full test suite passes
- ✅ No regressions introduced
- ✅ Tests remain deterministic

### CI Integration
- Tests run automatically in GitHub Actions
- Runtime is now <10s (well under 30s target)
- Clean output (no warning noise)

## Files Modified

1. **`pytest.ini`**: Added warning filter
2. **`server/tests/conftest.py`**: Added warning guardrail and optimization fixtures
3. **`server/tests/test_facts_acceptance_e2e.py`**: Added optimization fixtures
4. **`docs/FACTS_ACCEPTANCE_TESTS.md`**: Added warning policy documentation

## Future Optimizations (If Needed)

If further optimization is required:
1. **Session-scoped DB**: Could share DB setup across tests (but reduces isolation)
2. **In-memory SQLite**: Could use `:memory:` for even faster I/O (requires DB layer changes)
3. **Parallel execution**: Could run tests in parallel (requires careful isolation)

Current performance is excellent and meets all requirements.

