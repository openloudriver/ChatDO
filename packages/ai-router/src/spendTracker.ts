import { promises as fs } from "fs";
import { join } from "path";

export interface ProviderSpend {
  [providerId: string]: number; // e.g. { "openai-gpt5": 12.34 }
}

export interface CurrentMonthState {
  monthId: string; // "YYYY-MM"
  providers: ProviderSpend;
}

// For history; each month -> totals
export interface MonthlyHistoryEntry {
  monthId: string; // "YYYY-MM"
  providers: ProviderSpend;
  totalUsd: number;
}

export interface MonthlyHistory {
  [monthId: string]: MonthlyHistoryEntry;
}

// Use process.cwd() to get the repo root, then navigate to ai-router/data
// This works whether running from repo root or ai-router directory
const DATA_DIR = join(process.cwd().includes("packages/ai-router") 
  ? process.cwd() 
  : join(process.cwd(), "packages", "ai-router"), 
  "data");
const CURRENT_STATE_FILE = join(DATA_DIR, "ai_spend_state.json");
const HISTORY_FILE = join(DATA_DIR, "ai_spend_history.json");

// Ensure data directory exists
async function ensureDataDir(): Promise<void> {
  try {
    await fs.access(DATA_DIR);
  } catch {
    await fs.mkdir(DATA_DIR, { recursive: true });
  }
}

export function getCurrentMonthId(now: Date): string {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  return `${year}-${month}`;
}

export async function loadCurrentMonthState(): Promise<CurrentMonthState> {
  await ensureDataDir();
  try {
    const content = await fs.readFile(CURRENT_STATE_FILE, "utf-8");
    return JSON.parse(content);
  } catch {
    // First run or file doesn't exist
    const monthId = getCurrentMonthId(new Date());
    return {
      monthId,
      providers: {},
    };
  }
}

export async function saveCurrentMonthState(state: CurrentMonthState): Promise<void> {
  await ensureDataDir();
  await fs.writeFile(CURRENT_STATE_FILE, JSON.stringify(state, null, 2), "utf-8");
}

export async function loadHistory(): Promise<MonthlyHistory> {
  await ensureDataDir();
  try {
    const content = await fs.readFile(HISTORY_FILE, "utf-8");
    return JSON.parse(content);
  } catch {
    return {};
  }
}

export async function saveHistory(history: MonthlyHistory): Promise<void> {
  await ensureDataDir();
  await fs.writeFile(HISTORY_FILE, JSON.stringify(history, null, 2), "utf-8");
}

/**
 * Record usage for a single AI call.
 * - providerId: e.g. "openai-gpt5"
 * - modelId:    e.g. "gpt-5" (not needed for spend display, but useful for history if you want to extend later)
 * - costUsd:    calculated cost of this call
 *
 * This function should:
 *  - Load current month state
 *  - If month changed since last state, roll the old month into history, save history, and reset state for new month
 *  - Add costUsd to the provider's total for the current month
 *  - Save current month state
 */
export async function recordUsage(
  providerId: string,
  modelId: string,
  costUsd: number,
  at?: Date
): Promise<void> {
  const now = at || new Date();
  const currentMonthId = getCurrentMonthId(now);

  let state = await loadCurrentMonthState();

  // Check if month has changed
  if (state.monthId && state.monthId !== currentMonthId) {
    // Roll over: save previous month to history
    const totalUsd = Object.values(state.providers).reduce((sum, val) => sum + val, 0);
    if (totalUsd > 0) {
      const history = await loadHistory();
      history[state.monthId] = {
        monthId: state.monthId,
        providers: { ...state.providers },
        totalUsd,
      };
      await saveHistory(history);
    }

    // Reset state for new month
    state = {
      monthId: currentMonthId,
      providers: {},
    };
  } else if (!state.monthId) {
    // First run: initialize with current month
    state.monthId = currentMonthId;
    state.providers = {};
  }

  // Add cost to provider total
  state.providers[providerId] = (state.providers[providerId] || 0) + costUsd;

  // Save updated state
  await saveCurrentMonthState(state);
}

/**
 * Return current month info, including per-provider and total.
 */
export async function getCurrentMonthSpend(): Promise<MonthlyHistoryEntry> {
  const state = await loadCurrentMonthState();
  const monthId = state.monthId || getCurrentMonthId(new Date());
  const totalUsd = Object.values(state.providers).reduce((sum, val) => sum + val, 0);

  return {
    monthId,
    providers: { ...state.providers },
    totalUsd,
  };
}

/**
 * Return the full history map (for future graphs).
 */
export async function getMonthlyHistory(): Promise<MonthlyHistory> {
  return await loadHistory();
}

