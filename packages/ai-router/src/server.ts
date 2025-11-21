import "dotenv/config";
import express from "express";
import bodyParser from "body-parser";
import cors from "cors";
import { runTask, AiRouterInput } from "./index";
import { getCurrentMonthSpend, getMonthlyHistory } from "./spendTracker";
import { callOllamaSummary } from "./providers/ollama";

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
    res.json({
      ok: true,
      month: current.monthId,
      totalUsd: current.totalUsd,
      providers: Object.entries(current.providers).map(([id, usd]) => {
        // Map provider IDs to nicer labels
        const labelMap: Record<string, string> = {
          "openai-gpt5": "OpenAI GPT-5",
          "gab-ai": "Gab AI",
          "anthropic-claude-sonnet": "Anthropic Claude",
          "grok-code": "Grok Code",
          "gemini-pro": "Gemini Pro",
          "mistral-large": "Mistral Large",
          "llama-local": "Llama Local",
          "ollama-local": "Ollama Local",
        };
        return {
          id,
          label: labelMap[id] || id,
          usd,
        };
      }),
    });
  } catch (err: any) {
    console.error("[AI-Router] /v1/ai/spend/monthly error:", err);
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

app.post("/v1/ai/ollama/summarize", async (req, res) => {
  try {
    const { systemPrompt, userPrompt } = req.body;
    if (!systemPrompt || !userPrompt) {
      res.status(400).json({
        ok: false,
        error: "Missing required fields: systemPrompt, userPrompt",
      });
      return;
    }
    const summary = await callOllamaSummary(systemPrompt, userPrompt);
    res.json({
      ok: true,
      summary,
    });
  } catch (err: any) {
    console.error("[AI-Router] /v1/ai/ollama/summarize error:", err);
    res.status(500).json({ ok: false, error: err?.message ?? "Unknown error" });
  }
});

const port = process.env.AI_ROUTER_PORT || 8081;
app.listen(port, () => {
  console.log(`AI-Router listening on http://localhost:${port}`);
});

