# Deep-Link Torture Test Report

## Test Suite Overview

**Objective**: Prove deep linking is reliable under 500+ distinct citation navigations.

**Status**: Test suite created and ready to run.

---

## Automated Test Suite

### Files Created

1. **`tests/e2e/deep_link_torture.spec.ts`** - Main Playwright test suite
2. **`tests/fixtures/deep_link_topics.json`** - Topic bank with 20+ topics and transformations
3. **`tests/e2e/playwright.config.ts`** - Playwright configuration
4. **`tests/e2e/package.json`** - Test dependencies

### Test Configuration

- **Number of Chats**: 20
- **Messages per Chat**: 50
- **Queries per Chat**: 10
- **Target Total Clicks**: 500
- **Modes**: Normal, Slow 3G, CPU Throttled

### Validations Per Click

Each citation click validates:
- ✅ Navigation to expected chat
- ✅ URL hash updates correctly
- ✅ Target element exists (`#message-${uuid}`)
- ✅ Element is in viewport
- ✅ Anchor text matches expected
- ✅ No console errors
- ✅ Observer cleanup

---

## Manual Test Cases (20 Quick Probes)

Run these manually to verify deep linking works:

1. **"what did I say about candy"** - Should navigate to message about candy
2. **"remind me my top candies"** - Should show ranked list with citations
3. **"I forgot the candy list, cite it"** - Should cite each item
4. **"what's my #2 candy"** - Should navigate to second-ranked candy message
5. **"what's my favorite chocolate bar"** - Should navigate to chocolate message
6. **"did I say Hershey or Hersheys?"** - Should handle typo variation
7. **"tell me my favorite candies again but only list them"** - Should show list with citations
8. **"what did I say about Monero vs Bitcoin? cite"** - Should navigate to comparison message
9. **"where did I mention electricity cost? cite"** - Should navigate to electricity message
10. **"what did I say about retirement date? cite"** - Should navigate to date message
11. **"show me the exact message where I said the paycheck schedule"** - Should navigate to paycheck message
12. **"I said something about 30W miners—find it and cite"** - Should navigate to power consumption message
13. **"what did I say about deep-link protocol? cite"** - Should navigate to technical message
14. **"in Spanish: ¿Cuáles son mis dulces favoritos? cítalo"** - Should handle multilingual
15. **"all caps: WHAT ARE MY FAVORITE CANDIES? CITE"** - Should handle casing
16. **"typo: whats my favrite candys cte"** - Should handle typos
17. **"emoji: favorite candies 🍫 cite"** - Should handle emoji
18. **"cite every sentence"** - Should cite multiple items
19. **"open the citation in a new tab and confirm it scrolls right"** - Should work in new tab
20. **"click citations rapidly and confirm highlights don't stack weirdly"** - Should handle rapid clicks

---

## Setup Instructions

### 1. Install Playwright

```bash
cd tests/e2e
npm install
npx playwright install chromium
```

### 2. Run Tests

```bash
# Run torture tests
npm run test:torture

# Run with visible browser
npm run test:torture:headed
```

### 3. View Results

Results are saved to `artifacts/DEEP_LINK_TORTURE_RESULTS-*.json`

---

## Expected Results

- **Total Clicks**: 500+
- **Pass Rate**: 100% (0 failures)
- **Average Navigation Time**: < 2 seconds
- **Failure Reasons**: None

---

## Debugging Failures

If a test fails:

1. Check `artifacts/failure-*.png` for screenshot
2. Check `artifacts/failure-*.html` for HTML snapshot
3. Review `DEEP_LINK_TORTURE_RESULTS-*.json` for failure details
4. Check browser console for errors
5. Verify `message_uuid` is present in API response
6. Verify element IDs match `message-${uuid}` pattern

---

## Next Steps

1. **Run the test suite** to validate deep linking
2. **Fix any failures** that occur
3. **Iterate** until 100% pass rate
4. **Document** any edge cases found

---

## Notes

- The test suite uses deterministic seeding for reproducibility
- Each message includes a unique anchor token for validation
- Tests run sequentially to avoid race conditions
- Network and CPU throttling simulate real-world conditions

