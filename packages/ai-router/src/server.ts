import express from "express";
import bodyParser from "body-parser";
import { runTask, AiRouterInput } from "./index";

const app = express();
app.use(bodyParser.json());

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

const port = process.env.AI_ROUTER_PORT || 8081;
app.listen(port, () => {
  console.log(`AI-Router listening on http://localhost:${port}`);
});

