import "dotenv/config";
import express from "express";
import bodyParser from "body-parser";
import cors from "cors";
import { runTask, AiRouterInput } from "./index";
import { getCurrentMonthSpend, getMonthlyHistory, recordUsage } from "./spendTracker";

const app = express();
app.use(cors({
  origin: ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
  credentials: true
}));
// Increase body size limit to handle large scraped content (50MB)
app.use(bodyParser.json({ limit: '50mb' }));

app.post("/v1/ai/run", async (req, res) => {
  const input = req.body as AiRouterInput;

  try {
    const result = await runTask(input);
    res.json({
      ok: true,
      providerId: result.providerId,
      modelId: result.modelId,
      provider: result.providerId, // For backward compatibility and clarity
      model: result.modelId, // For backward compatibility and clarity
      output: result.output,
    });
  } catch (err: any) {
    console.error("[AI-Router] Error:", err);

    res.status(500).json({
      ok: false,
      error: err?.message ?? "Unknown error",
    });
  }
});

app.get("/v1/ai/spend/monthly", async (_req, res) => {
  try {
    const current = await getCurrentMonthSpend();
    
    // Map provider IDs to nicer labels (model names only, no company names)
    // NOTE: openai-gpt5-mini removed - Librarian no longer uses GPT-5 Mini
    const labelMap: Record<string, string> = {
      "openai-gpt5": "GPT-5",
      "openai-gpt5-nano": "GPT-5 Nano",
      "anthropic-claude-sonnet": "Claude Sonnet",
      "grok-code": "Grok Code",
      "gemini-pro": "Gemini Pro",
      "mistral-large": "Mistral Large",
      "brave-pro": "Brave-Pro AI",
    };
    
    // Always include GPT-5, GPT-5 Nano, and Brave Pro AI, even if they have $0 spend
    // Only show providers that have been used
    const providers: Array<{ id: string; label: string; usd: number }> = [];
    
    // Add GPT-5 (always show)
    providers.push({
      id: "openai-gpt5",
      label: labelMap["openai-gpt5"] || "GPT-5",
      usd: current.providers["openai-gpt5"] || 0,
    });
    
    // Add GPT-5 Nano (always show)
    providers.push({
      id: "openai-gpt5-nano",
      label: labelMap["openai-gpt5-nano"] || "GPT-5 Nano",
      usd: current.providers["openai-gpt5-nano"] || 0,
    });
    
    // Add Brave Pro AI (always show)
    providers.push({
      id: "brave-pro",
      label: labelMap["brave-pro"] || "Brave-Pro AI",
      usd: current.providers["brave-pro"] || 0,
    });
    
    // Add any other providers that have been used
    // Filter out deprecated providers (e.g., openai-whisper-1, openai-gpt5-mini)
    const deprecatedProviders = new Set(["openai-whisper-1", "openai-gpt5-mini"]);
    for (const [id, usd] of Object.entries(current.providers)) {
      if (id !== "openai-gpt5" && id !== "openai-gpt5-nano" && id !== "brave-pro" && !deprecatedProviders.has(id)) {
        providers.push({
          id,
          label: labelMap[id] || id,
          usd,
        });
      }
    }
    
    // Recalculate total excluding deprecated providers
    const totalUsd = providers.reduce((sum, p) => sum + p.usd, 0);
    
    res.json({
      ok: true,
      month: current.monthId,
      totalUsd,
      providers,
    });
  } catch (err: any) {
    console.error("[AI-Router] /v1/ai/spend/monthly error:", err);
    res.status(500).json({ ok: false, error: err?.message ?? "Unknown error" });
  }
});

app.post("/v1/ai/spend/record", async (req, res) => {
  try {
    const { providerId, modelId, costUsd } = req.body;
    
    if (!providerId || typeof costUsd !== "number") {
      res.status(400).json({
        ok: false,
        error: "Missing required fields: providerId, costUsd",
      });
      return;
    }
    
    await recordUsage(providerId, modelId || "unknown", costUsd);
    
    res.json({
      ok: true,
      message: "Usage recorded",
    });
  } catch (err: any) {
    console.error("[AI-Router] /v1/ai/spend/record error:", err);
    res.status(500).json({ ok: false, error: err?.message ?? "Unknown error" });
  }
});

app.get("/v1/ai/spend/history", async (_req, res) => {
  try {
    const history = await getMonthlyHistory();
    res.json({
      ok: true,
      months: Object.values(history),
    });
  } catch (err: any) {
    console.error("[AI-Router] /v1/ai/spend/history error:", err);
    res.status(500).json({ ok: false, error: err?.message ?? "Unknown error" });
  }
});

const port = process.env.AI_ROUTER_PORT || 8081;
app.listen(port, () => {
  console.log(`AI-Router listening on http://localhost:${port}`);
});

