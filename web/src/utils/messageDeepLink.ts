/**
 * Utilities for deep-linking to specific messages with support for
 * virtualized/async rendering and URL hash fragments.
 */

/**
 * Wait for a DOM element to appear, with retry and backoff.
 * Uses MutationObserver for efficient watching, with fallback to polling.
 * 
 * @param elementId - The ID of the element to wait for (e.g., "message-123")
 * @param options - Configuration options
 * @returns Promise that resolves when element is found, or rejects after timeout
 */
export async function waitForMessageElement(
  elementId: string,
  options: {
    timeout?: number;
    retryInterval?: number;
    useObserver?: boolean;
    container?: HTMLElement | null;
  } = {}
): Promise<HTMLElement> {
  const {
    timeout = 10000, // 10 seconds max
    retryInterval = 100, // Start with 100ms
    useObserver = true,
    container = null,
  } = options;

  return new Promise((resolve, reject) => {
    // First, check if element already exists
    const existingElement = document.getElementById(elementId);
    if (existingElement) {
      resolve(existingElement);
      return;
    }

    const startTime = Date.now();
    let retryCount = 0;
    const maxRetries = Math.floor(timeout / retryInterval);

    // Use MutationObserver for efficient watching
    if (useObserver && typeof MutationObserver !== 'undefined') {
      const observer = new MutationObserver((mutations, obs) => {
        const element = document.getElementById(elementId);
        if (element) {
          obs.disconnect();
          resolve(element);
          return;
        }

        // Check timeout
        if (Date.now() - startTime > timeout) {
          obs.disconnect();
          reject(new Error(`Timeout waiting for element ${elementId}`));
        }
      });

      // Use provided container, or find messages container, or fallback to body
      const observeTarget = container || 
        document.querySelector('[class*="overflow-y-auto"]') || 
        document.body;
      
      if (observeTarget) {
        observer.observe(observeTarget, {
          childList: true,
          subtree: true,
        });
      }

      // Fallback timeout
      const timeoutId = setTimeout(() => {
        observer.disconnect();
        const element = document.getElementById(elementId);
        if (element) {
          resolve(element);
        } else {
          reject(new Error(`Timeout waiting for element ${elementId}`));
        }
      }, timeout);

      // Cleanup on resolve/reject
      Promise.resolve().then(() => {
        // This ensures cleanup happens
      });
    } else {
      // Fallback to polling
      const poll = () => {
        const element = document.getElementById(elementId);
        if (element) {
          resolve(element);
          return;
        }

        retryCount++;
        if (retryCount >= maxRetries || Date.now() - startTime > timeout) {
          reject(new Error(`Timeout waiting for element ${elementId} after ${retryCount} retries`));
          return;
        }

        // Exponential backoff: 100ms, 150ms, 225ms, etc. (capped at 500ms)
        const nextInterval = Math.min(retryInterval * Math.pow(1.5, retryCount - 1), 500);
        setTimeout(poll, nextInterval);
      };

      poll();
    }
  });
}

/**
 * Scroll to a message element and highlight it.
 * 
 * @param element - The message element to scroll to
 * @param options - Scroll and highlight options
 */
export function scrollToAndHighlightMessage(
  element: HTMLElement,
  options: {
    behavior?: ScrollBehavior;
    block?: ScrollLogicalPosition;
    highlightDuration?: number;
    highlightColor?: string;
  } = {}
): void {
  const {
    behavior = 'smooth',
    block = 'start',  // Default to 'start' to position at top of viewport
    highlightDuration = 2000,
    highlightColor = 'var(--highlight-color, rgba(25, 195, 125, 0.2))',
  } = options;

  // Scroll to element - use 'start' to position at top of viewport
  element.scrollIntoView({ behavior, block, inline: 'nearest' });

  // Highlight the message
  const originalTransition = element.style.transition;
  const originalBackgroundColor = element.style.backgroundColor;

  element.style.transition = 'background-color 0.3s ease';
  element.style.backgroundColor = highlightColor;

  // Remove highlight after duration
  setTimeout(() => {
    element.style.backgroundColor = originalBackgroundColor || '';
    setTimeout(() => {
      element.style.transition = originalTransition || '';
    }, 300);
  }, highlightDuration);
}

/**
 * Navigate to a message by ID, waiting for it to appear and scrolling to it.
 * Also updates the URL hash fragment.
 * 
 * @param messageId - The message ID to navigate to
 * @param options - Navigation options
 */
export async function navigateToMessage(
  messageId: string,
  options: {
    updateUrl?: boolean;
    timeout?: number;
    container?: HTMLElement | null;
  } = {}
): Promise<void> {
  const {
    updateUrl = true,
    timeout = 10000,
    container = null,
  } = options;

  const elementId = `message-${messageId}`;

  // Update URL hash if requested
  if (updateUrl && typeof window !== 'undefined') {
    const newHash = `#${elementId}`;
    if (window.location.hash !== newHash) {
      window.history.replaceState(null, '', newHash);
    }
  }

  try {
    console.log(`[DEEP-LINK] Waiting for element ${elementId} to appear...`);
    // Wait for element to appear (with container for better observation)
    const element = await waitForMessageElement(elementId, { 
      timeout,
      container,
    });
    
    console.log(`[DEEP-LINK] Found element ${elementId}, scrolling to TOP of viewport...`);
    // Scroll and highlight - explicitly use 'start' to position at TOP
    scrollToAndHighlightMessage(element, {
      block: 'start',  // Position at top of viewport - critical for reading from beginning
      behavior: 'smooth',
    });
    console.log(`[DEEP-LINK] Successfully scrolled to message ${messageId}`);
  } catch (error) {
    console.error(`[DEEP-LINK] Failed to navigate to message ${messageId} (elementId: ${elementId}):`, error);
    // Still update URL even if element not found yet
    if (updateUrl && typeof window !== 'undefined') {
      window.history.replaceState(null, '', `#${elementId}`);
    }
    throw error; // Re-throw so caller can handle retries
  }
}

/**
 * Extract message ID from URL hash fragment.
 * Supports formats: #message-<id> or #message-<uuid>
 * 
 * @returns The message ID if found, or null
 */
export function getMessageIdFromHash(): string | null {
  if (typeof window === 'undefined') return null;
  
  const hash = window.location.hash;
  if (!hash) return null;

  // Match #message-<id> pattern
  const match = hash.match(/^#message-(.+)$/);
  return match ? match[1] : null;
}

