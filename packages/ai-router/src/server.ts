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
    const labelMap: Record<string, string> = {
      "openai-gpt5": "GPT-5",
      "anthropic-claude-sonnet": "Claude Sonnet",
      "grok-code": "Grok Code",
      "gemini-pro": "Gemini Pro",
      "mistral-large": "Mistral Large",
      "brave-pro": "Brave-Pro AI",
    };
    
    // Always include GPT-5, even if it has $0 spend
    // Only show providers that have been used
    const providers: Array<{ id: string; label: string; usd: number }> = [];
    
    // Add GPT-5 (always show)
    providers.push({
      id: "openai-gpt5",
      label: labelMap["openai-gpt5"] || "GPT-5",
      usd: current.providers["openai-gpt5"] || 0,
    });
    
    // Add any other providers that have been used
    // Filter out deprecated providers (e.g., openai-whisper-1)
    const deprecatedProviders = new Set(["openai-whisper-1"]);
    for (const [id, usd] of Object.entries(current.providers)) {
      if (id !== "openai-gpt5" && !deprecatedProviders.has(id)) {
        providers.push({
          id,
          label: labelMap[id] || id,
          usd,
        });
      }
    }
    
    res.json({
      ok: true,
      month: current.monthId,
      totalUsd: current.totalUsd,
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

