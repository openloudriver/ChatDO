import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for Deep-Link Torture Tests
 */
export default defineConfig({
  testDir: './',
  fullyParallel: false, // Run sequentially to avoid conflicts
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // Single worker for stability
  reporter: [
    ['html', { outputFolder: '../../artifacts/playwright-report' }],
    ['json', { outputFile: '../../artifacts/test-results.json' }],
    ['list'],
  ],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 60000, // Increased for API calls
    navigationTimeout: 60000, // Increased for page loads
  },
  
  timeout: 60000, // 1 minute per test
  
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  
  // Web servers are already running - no need to start them
  // webServer: [], // Disabled - servers are running externally
});
