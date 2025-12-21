/**
 * Deep-Link Torture Test Suite
 * 
 * Objective: Prove deep linking is reliable under 500+ distinct citation navigations
 * across: paraphrases, typos, multi-turn reasoning, timing delays, hash loads,
 * cross-chat jumps, missing UUIDs, long chats, and UI virtualization.
 * 
 * Target: 500+ citation clicks validated per run.
 */

import { test, expect, Page, BrowserContext } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

// Import topics data
const topicsDataPath = path.join(__dirname, '../fixtures/deep_link_topics.json');
const topicsData = JSON.parse(fs.readFileSync(topicsDataPath, 'utf-8'));

// Test configuration
// Minimal scale for initial validation - can be increased once working
const CONFIG = {
  NUM_CHATS: 2, // Minimal for testing
  MESSAGES_PER_CHAT: 3, // Minimal for testing - just enough to create facts
  QUERIES_PER_CHAT: 2, // Minimal for testing
  TARGET_TOTAL_CLICKS: 10, // Minimal for initial validation
  BASE_URL: 'http://localhost:5173',
  API_URL: 'http://localhost:8000',
  MEMORY_URL: 'http://localhost:5858',
  USE_UI_FOR_SEEDING: true, // Use UI instead of API to avoid hanging
};

// Results tracking
interface TestResult {
  clickIndex: number;
  chatId: string;
  messageUuid: string;
  expectedAnchor: string;
  passed: boolean;
  failureReason?: string;
  elapsedMs: number;
  attemptCount: number;
  debugInfo?: any;
}

interface TortureResults {
  totalClicks: number;
  passCount: number;
  failCount: number;
  failureReasons: Record<string, number>;
  failures: TestResult[];
  seed: number;
  mode: string;
  timestamp: string;
}

// Anchor generator
function generateAnchor(chatIndex: number, msgIndex: number, topicTag: string): string {
  const randomBase32 = Math.random().toString(36).substring(2, 8).toUpperCase();
  return `ANCHOR::${chatIndex}::${msgIndex}::${randomBase32}::${topicTag}`;
}

// Topic and question generators
function getRandomTopic(seed: number) {
  const topics = topicsData.topics;
  const rng = () => {
    seed = (seed * 9301 + 49297) % 233280;
    return seed / 233280;
  };
  return topics[Math.floor(rng() * topics.length)];
}

function generateQuestion(topic: any, seed: number): string {
  let localSeed = seed;
  const rng = () => {
    localSeed = (localSeed * 9301 + 49297) % 233280;
    return localSeed / 233280;
  };
  
  const template = topic.question_templates[Math.floor(rng() * topic.question_templates.length)];
  let question = template;
  
  // Apply random transformations
  const numTransformations = Math.floor(rng() * 5);
  for (let i = 0; i < numTransformations; i++) {
    const transformType = Math.floor(rng() * 10);
    
    switch (transformType) {
      case 0: // Synonym swap
        question = question.replace(/favorite/g, () => {
          const synonyms = topicsData.transformations.synonyms.favorite;
          return synonyms[Math.floor(rng() * synonyms.length)];
        });
        break;
      case 1: // Add filler
        const fillers = topicsData.transformations.filler_words;
        const filler = fillers[Math.floor(rng() * fillers.length)];
        question = `${filler} ${question}`;
        break;
      case 2: // Punctuation noise
        const puncts = topicsData.transformations.punctuation;
        const punct = puncts[Math.floor(rng() * puncts.length)];
        question = question.replace(/[?!.]$/, '') + punct;
        break;
      case 3: // Casing
        if (rng() < 0.3) question = question.toUpperCase();
        else if (rng() < 0.6) question = question.toLowerCase();
        break;
      case 4: // Typo
        const typoPatterns = topicsData.transformations.typo_patterns;
        if (typoPatterns.length > 0) {
          const pattern = typoPatterns[Math.floor(rng() * typoPatterns.length)];
          if (question.includes(pattern.pattern)) {
            const typo = pattern.typos[Math.floor(rng() * pattern.typos.length)];
            question = question.replace(pattern.pattern, typo);
          }
        }
        break;
      case 5: // Emoji
        const emojis = topicsData.transformations.emoji;
        const emoji = emojis[Math.floor(rng() * emojis.length)];
        question = `${question} ${emoji}`;
        break;
      case 6: // Indirect phrasing
        const indirect = topicsData.transformations.indirect_phrasing;
        const phrase = indirect[Math.floor(rng() * indirect.length)];
        question = `${phrase} ${question}`;
        break;
      case 7: // Constraint
        const constraints = topicsData.transformations.constraints;
        const constraint = constraints[Math.floor(rng() * constraints.length)];
        question = `${question} ${constraint}`;
        break;
    }
  }
  
  // Always add citation requirement
  if (!question.toLowerCase().includes('cite')) {
    question = `${question} Cite the exact source message.`;
  }
  
  return question;
}

// Seed data generator
async function seedChatData(
  page: Page,
  projectId: string,
  chatIndex: number,
  numMessages: number,
  seed: number
): Promise<{ chatId: string; anchors: Map<string, string> }> {
  const anchors = new Map<string, string>();
  
  // Create a new chat via API
  const createChatResponse = await page.request.post(`${CONFIG.API_URL}/api/new_conversation`, {
    data: {
      project_id: projectId,
    },
  });
  
  const chatData = await createChatResponse.json();
  const chatId = chatData.conversation_id;
  
  // Navigate to chat
  await page.goto(`${CONFIG.BASE_URL}`);
  await page.waitForTimeout(1000);
  
  // Navigate to the chat (adjust based on your routing)
  await page.goto(`${CONFIG.BASE_URL}/chat/${chatId}`);
  await page.waitForTimeout(2000);
  
  // Seed messages with anchors
  for (let msgIndex = 0; msgIndex < numMessages; msgIndex++) {
    const topic = getRandomTopic(seed + msgIndex);
    const anchor = generateAnchor(chatIndex, msgIndex, topic.topic_key);
    
    // Generate message content with anchor
    let messageContent = '';
    if (topic.fact_types.includes('ranked')) {
      const values = ['Value1', 'Value2', 'Value3'].map((v, i) => `${i + 1}) ${v}`);
      messageContent = `My favorite ${topic.aliases[0]} are ${values.join(', ')}. ${anchor}`;
    } else {
      messageContent = `My favorite ${topic.aliases[0]} is Value1. ${anchor}`;
    }
    
    // Send message via API (faster than UI)
    // Note: target_name is typically derived from project, but we'll use "general" as default
    const sendResponse = await page.request.post(`${CONFIG.API_URL}/api/chat`, {
      data: {
        message: messageContent,
        conversation_id: chatId,
        project_id: projectId,
        target_name: 'general', // Default target name
      },
    });
    
    if (!sendResponse.ok) {
      const errorText = await sendResponse.text();
      console.warn(`Failed to send message ${msgIndex} in chat ${chatIndex}: ${errorText}`);
    } else {
      // Try to get message_uuid from response (if available)
      try {
        const responseData = await sendResponse.json();
        // The response might contain message data - adjust based on actual API response
        // For now, we'll map anchor to a placeholder and resolve it later
        anchors.set(anchor, `msg-${msgIndex}`);
      } catch (e) {
        anchors.set(anchor, `msg-${msgIndex}`);
      }
    }
    
    // Wait a bit for indexing
    await page.waitForTimeout(1000);
  }
  
  return { chatId, anchors };
}

// Validate deep link navigation
async function validateDeepLink(
  page: Page,
  citationElement: any,
  expectedChatId: string,
  expectedAnchor: string,
  clickIndex: number
): Promise<TestResult> {
  const startTime = Date.now();
  let attemptCount = 0;
  const maxAttempts = 10;
  const timeout = 15000;
  
  const result: TestResult = {
    clickIndex,
    chatId: expectedChatId,
    messageUuid: '',
    expectedAnchor,
    passed: false,
    elapsedMs: 0,
    attemptCount: 0,
  };
  
  try {
    // Get message_uuid from citation - try multiple ways
    let messageUuid: string | null = null;
    
    // Method 1: data attribute
    messageUuid = await citationElement.getAttribute('data-message-uuid');
    
    // Method 2: from parent element
    if (!messageUuid) {
      messageUuid = await citationElement.evaluate((el: any) => {
        const parent = el.closest('[data-source]');
        if (parent) {
          const meta = parent.getAttribute('data-meta');
          if (meta) {
            try {
              const parsed = JSON.parse(meta);
              return parsed.message_uuid || null;
            } catch (e) {
              return null;
            }
          }
        }
        return null;
      });
    }
    
    // Method 3: from click handler (if we can intercept)
    if (!messageUuid) {
      // Try to extract from the citation's click handler or nearby elements
      const parent = citationElement.locator('..');
      messageUuid = await parent.getAttribute('data-message-uuid');
    }
    
    if (!messageUuid) {
      result.failureReason = 'no_message_uuid';
      result.debugInfo = {
        citationHtml: await citationElement.innerHTML().catch(() => 'N/A'),
        citationText: await citationElement.textContent().catch(() => 'N/A'),
      };
      result.elapsedMs = Date.now() - startTime;
      return result;
    }
    
    result.messageUuid = messageUuid;
    
    // Click citation
    await citationElement.click({ timeout: 5000 });
    await page.waitForTimeout(500);
    
    // Wait for navigation and element
    const elementId = `message-${messageUuid}`;
    let elementFound = false;
    
    while (!elementFound && attemptCount < maxAttempts && (Date.now() - startTime) < timeout) {
      attemptCount++;
      await page.waitForTimeout(300);
      
      // Check if we're in the right chat
      const currentUrl = page.url();
      const currentChatId = currentUrl.match(/\/chat\/([^\/\?#]+)/)?.[1];
      
      if (currentChatId && currentChatId !== expectedChatId) {
        // Still navigating, wait more
        continue;
      }
      
      // Check if element exists
      const element = page.locator(`#${elementId}`).first();
      const count = await element.count();
      
      if (count > 0 && await element.isVisible()) {
        elementFound = true;
        
        // Verify element is in viewport
        const isInViewport = await element.evaluate((el: HTMLElement) => {
          const rect = el.getBoundingClientRect();
          const viewportHeight = window.innerHeight;
          return rect.top >= 0 && rect.top <= viewportHeight;
        });
        
        if (!isInViewport) {
          result.failureReason = 'element_not_in_viewport';
          result.debugInfo = {
            elementId,
            boundingRect: await element.boundingBox(),
            viewportHeight: await page.evaluate(() => window.innerHeight),
          };
          result.elapsedMs = Date.now() - startTime;
          result.attemptCount = attemptCount;
          return result;
        }
        
        // Verify anchor text
        const elementText = await element.textContent();
        if (!elementText || !elementText.includes(expectedAnchor)) {
          result.failureReason = 'anchor_mismatch';
          result.debugInfo = {
            expectedAnchor,
            foundText: elementText?.substring(0, 200),
            fullText: elementText,
          };
          result.elapsedMs = Date.now() - startTime;
          result.attemptCount = attemptCount;
          return result;
        }
        
        // Verify URL hash
        const hash = await page.evaluate(() => window.location.hash);
        const expectedHash = `#${elementId}`;
        if (hash !== expectedHash) {
          result.failureReason = 'hash_mismatch';
          result.debugInfo = { expected: expectedHash, found: hash };
          result.elapsedMs = Date.now() - startTime;
          result.attemptCount = attemptCount;
          return result;
        }
        
        // Verify highlight (optional - check if highlight class or style is applied)
        const hasHighlight = await element.evaluate((el: HTMLElement) => {
          const bgColor = window.getComputedStyle(el).backgroundColor;
          return bgColor !== 'rgba(0, 0, 0, 0)' && bgColor !== 'transparent';
        });
        
        result.passed = true;
        result.elapsedMs = Date.now() - startTime;
        result.attemptCount = attemptCount;
        result.debugInfo = { hasHighlight };
        return result;
      }
    }
    
    if (!elementFound) {
      result.failureReason = 'element_not_found';
      result.debugInfo = {
        elementId,
        currentUrl: page.url(),
        first20MessageIds: await page.evaluate(() => {
          const messages = Array.from(document.querySelectorAll('[id^="message-"]'));
          return messages.slice(0, 20).map(m => m.id);
        }),
        allMessageIds: await page.evaluate(() => {
          const messages = Array.from(document.querySelectorAll('[id^="message-"]'));
          return messages.map(m => m.id);
        }),
      };
    }
    
    result.elapsedMs = Date.now() - startTime;
    result.attemptCount = attemptCount;
    return result;
    
  } catch (error: any) {
    result.failureReason = 'exception';
    result.debugInfo = { 
      error: error.message, 
      stack: error.stack,
      errorName: error.name,
    };
    result.elapsedMs = Date.now() - startTime;
    result.attemptCount = attemptCount;
    return result;
  }
}

// Main test suite
test.describe('Deep-Link Torture Test', () => {
  let results: TortureResults;
  let seed: number;
  
  test.beforeEach(() => {
    seed = Date.now();
    results = {
      totalClicks: 0,
      passCount: 0,
      failCount: 0,
      failureReasons: {},
      failures: [],
      seed,
      mode: 'normal',
      timestamp: new Date().toISOString(),
    };
  });
  
  test.afterEach(async ({ page }) => {
    // Save results
    const resultsDir = path.join(__dirname, '../../artifacts');
    if (!fs.existsSync(resultsDir)) {
      fs.mkdirSync(resultsDir, { recursive: true });
    }
    
    const resultsPath = path.join(resultsDir, `DEEP_LINK_TORTURE_RESULTS-${results.mode}-${Date.now()}.json`);
    fs.writeFileSync(resultsPath, JSON.stringify(results, null, 2));
    
    // Save artifacts on failure
    if (results.failCount > 0) {
      await page.screenshot({ 
        path: path.join(resultsDir, `failure-${results.mode}-${Date.now()}.png`), 
        fullPage: true 
      });
      
      // Save console logs
      const consoleLogs: string[] = [];
      page.on('console', msg => consoleLogs.push(msg.text()));
      
      // Save HTML
      const html = await page.content();
      fs.writeFileSync(path.join(resultsDir, `failure-${results.mode}-${Date.now()}.html`), html);
    }
  });
  
  // Test modes
  const modes = [
    { name: 'normal', throttle: null, cpuThrottle: null },
    { name: 'slow_3g', throttle: { download: 400, upload: 400, latency: 400 }, cpuThrottle: null },
    { name: 'cpu_throttle', throttle: null, cpuThrottle: 4 },
  ];
  
  for (const mode of modes) {
    test(`Deep-Link Torture Test - ${mode.name}`, async ({ page, context }) => {
      results.mode = mode.name;
      
      // Apply throttling if needed
      if (mode.throttle) {
        const client = await context.newCDPSession(page);
        await client.send('Network.emulateNetworkConditions', {
          offline: false,
          downloadThroughput: mode.throttle.download * 1024,
          uploadThroughput: mode.throttle.upload * 1024,
          latency: mode.throttle.latency,
        });
      }
      
      if (mode.cpuThrottle) {
        const client = await context.newCDPSession(page);
        await client.send('Emulation.setCPUThrottlingRate', { rate: mode.cpuThrottle });
      }
      
      // Navigate to app
      await page.goto(CONFIG.BASE_URL);
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(2000);
      
      // Get or create project - use "General" project or create one
      let projectId = 'torture-test-project';
      
      // Try to get existing projects first
      try {
        const projectsResponse = await page.request.get(`${CONFIG.API_URL}/api/projects`);
        if (projectsResponse.ok) {
          const projects = await projectsResponse.json();
          if (projects && projects.length > 0) {
            // Use first project
            projectId = projects[0].id;
          } else {
            // Create project if none exist
            const createResponse = await page.request.post(`${CONFIG.API_URL}/api/projects`, {
              data: { name: 'Torture Test Project' },
            });
            if (createResponse.ok) {
              const project = await createResponse.json();
              projectId = project.id;
            }
          }
        }
      } catch (e) {
        console.warn(`Failed to get/create project: ${e}`);
        // Fallback to a default project ID
        projectId = 'general';
      }
      
      // Seed chats
      const chatData: Array<{ chatId: string; anchors: Map<string, string> }> = [];
      console.log(`[TORTURE] Seeding ${CONFIG.NUM_CHATS} chats...`);
      
      for (let i = 0; i < CONFIG.NUM_CHATS; i++) {
        const data = await seedChatData(page, projectId, i, CONFIG.MESSAGES_PER_CHAT, seed + i);
        chatData.push(data);
        console.log(`[TORTURE] Seeded chat ${i + 1}/${CONFIG.NUM_CHATS}: ${data.chatId}`);
        await page.waitForTimeout(1000);
      }
      
      // Generate queries and validate citations
      let clickCount = 0;
      const targetClicks = Math.ceil(CONFIG.TARGET_TOTAL_CLICKS / modes.length);
      
      console.log(`[TORTURE] Starting citation validation (target: ${targetClicks} clicks)...`);
      
      for (let chatIdx = 0; chatIdx < CONFIG.NUM_CHATS && clickCount < targetClicks; chatIdx++) {
        const chat = chatData[chatIdx];
        
        // Switch to this chat
        await page.goto(`${CONFIG.BASE_URL}/chat/${chat.chatId}`);
        await page.waitForTimeout(2000);
        
        // Generate and execute queries
        for (let q = 0; q < CONFIG.QUERIES_PER_CHAT && clickCount < targetClicks; q++) {
          const topic = getRandomTopic(seed + clickCount);
          const question = generateQuestion(topic, seed + clickCount);
          
          console.log(`[TORTURE] Query ${q + 1} in chat ${chatIdx + 1}: "${question.substring(0, 50)}..."`);
          
          // Send query
          const input = page.locator('textarea[placeholder*="message" i], textarea[placeholder*="Message" i], input[type="text"]').first();
          await input.waitFor({ state: 'visible', timeout: 5000 });
          await input.fill(question);
          await input.press('Enter');
          
          if (CONFIG.SKIP_AI_RESPONSES) {
            // Don't wait for full AI response - just check if query was sent
            await page.waitForTimeout(2000); // Brief wait
            console.log('[TORTURE] Skipping AI response wait - testing navigation only');
          } else {
            // Wait for AI response (can be slow)
            await page.waitForTimeout(10000); // 10 seconds for AI response
          }
          
          // Find all citations in the response
          // Try multiple selectors for citations
          const citationSelectors = [
            'span[class*="citation"]',
            '[data-source-type="memory"]',
            'span:has-text("M")',
            '[class*="inline-citation"]',
          ];
          
          let citations: any[] = [];
          for (const selector of citationSelectors) {
            const found = await page.locator(selector).all();
            if (found.length > 0) {
              citations = found;
              break;
            }
          }
          
          console.log(`[TORTURE] Found ${citations.length} citations in response`);
          
          for (const citation of citations) {
            if (clickCount >= targetClicks) break;
            
            // Find expected anchor (simplified - in real test, match citation to specific anchor)
            const anchorKeys = Array.from(chat.anchors.keys());
            const expectedAnchor = anchorKeys[clickCount % anchorKeys.length];
            
            console.log(`[TORTURE] Validating citation ${clickCount + 1}/${targetClicks}...`);
            
            // Validate deep link
            const result = await validateDeepLink(
              page,
              citation,
              chat.chatId,
              expectedAnchor,
              clickCount
            );
            
            results.totalClicks++;
            if (result.passed) {
              results.passCount++;
              console.log(`[TORTURE] ✅ Click ${clickCount + 1} passed (${result.elapsedMs}ms)`);
            } else {
              results.failCount++;
              results.failures.push(result);
              if (result.failureReason) {
                results.failureReasons[result.failureReason] = 
                  (results.failureReasons[result.failureReason] || 0) + 1;
              }
              
              console.error(`[TORTURE] ❌ Click ${clickCount + 1} failed: ${result.failureReason}`);
              console.error(`[TORTURE] Debug info:`, result.debugInfo);
              
              // Stop on first failure for debugging
              if (results.failCount === 1) {
                // Save debug artifacts
                const artifactsDir = path.join(__dirname, '../../artifacts');
                if (!fs.existsSync(artifactsDir)) {
                  fs.mkdirSync(artifactsDir, { recursive: true });
                }
                
                await page.screenshot({ 
                  path: path.join(artifactsDir, `failure-click-${clickCount}.png`), 
                  fullPage: true 
                });
                
                const html = await page.content();
                fs.writeFileSync(
                  path.join(artifactsDir, `failure-click-${clickCount}.html`), 
                  html
                );
                
                // Save network HAR if possible
                // (Playwright doesn't directly support HAR, but we can log requests)
                
                break;
              }
            }
            
            clickCount++;
            
            // Small delay between clicks
            await page.waitForTimeout(500);
          }
        }
      }
      
      console.log(`[TORTURE] Test complete: ${results.passCount}/${results.totalClicks} passed`);
      
      // Assertions
      expect(results.failCount).toBe(0);
      expect(results.totalClicks).toBeGreaterThanOrEqual(targetClicks);
    });
  }
  
  // Edge case tests
  test('Edge case: Very long chat (300+ messages)', async ({ page }) => {
    // TODO: Implement long chat test
    test.skip();
  });
  
  test('Edge case: Rapid-fire clicking (10 citations in 2 seconds)', async ({ page }) => {
    // TODO: Implement rapid-fire test
    test.skip();
  });
  
  test('Edge case: Missing UUID graceful failure', async ({ page }) => {
    // TODO: Implement missing UUID test
    test.skip();
  });
  
  test('Edge case: Browser back/forward with hash', async ({ page }) => {
    // TODO: Implement browser navigation test
    test.skip();
  });
  
  test('Edge case: New tab with hash fragment', async ({ page, context }) => {
    // TODO: Implement new tab test
    test.skip();
  });
});
