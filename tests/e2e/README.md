# Deep-Link Torture Test Suite

## Overview

This test suite validates deep-linking functionality under extreme conditions with 500+ citation navigations across various scenarios.

## Setup

1. Install Playwright:
```bash
cd tests/e2e
npm install
npx playwright install chromium
```

2. Ensure all servers are running:
- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- Memory Service: `http://localhost:5858`

## Running Tests

```bash
# Run all torture tests
npm run test:torture

# Run with browser visible
npm run test:torture:headed

# Run in debug mode
npm run test:debug
```

## Test Modes

The suite runs in 3 modes:
1. **Normal** - Standard conditions
2. **Slow 3G** - Network throttled
3. **CPU Throttle** - CPU throttled 4x

Each mode targets ~167 clicks (500 total / 3 modes).

## Results

Results are saved to:
- `artifacts/DEEP_LINK_TORTURE_RESULTS-{mode}-{timestamp}.json`
- `artifacts/failure-*.png` (screenshots)
- `artifacts/failure-*.html` (HTML snapshots)

## Manual Test Cases

See `DEEP_LINK_TORTURE_REPORT.md` for 20 manual test cases to run.

