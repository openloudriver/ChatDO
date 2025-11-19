import OpenAI from "openai";
import {
  AiProvider,
  AiRouterInput,
  AiRouterResult,
} from "../types";

const client = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
  baseURL: process.env.OPENAI_BASE_URL || "https://api.openai.com/v1",
});

export const openAiGpt5Provider: AiProvider = {
  id: "openai-gpt5",
  label: "OpenAI GPT-5",
  costTier: "premium",
  maxContextTokens: 200_000,
  specialties: [
    "long_planning",
    "general_chat",
    "doc_draft",
    "tool_orchestration",
    "code_edit",
    "code_gen",
    "summarize",
    "review",
  ],

  supportsPrivacyLevel(level) {
    return level === "normal" || level === "strict";
  },

  async invoke(input: AiRouterInput): Promise<AiRouterResult> {
    const messages = input.input.messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    // Get model from routing rules (passed via systemHint or determined by intent)
    // Default to gpt-5 if not specified
    const modelId = (input.input.systemHint as string) || "gpt-5";

    // Sanity check: only gpt-5 is allowed
    if (modelId !== "gpt-5") {
      throw new Error(
        `Invalid model: ${modelId}. ChatDO only supports gpt-5. Codex models are not supported.`
      );
    }

    // gpt-5 uses v1/chat/completions endpoint
    // gpt-5 models don't support custom temperature - only default (1)
    const response = await client.chat.completions.create({
      model: modelId,
      messages,
    });

    const content =
      response.choices[0]?.message?.content ?? "[openai-gpt5] empty response";

    // Extract usage information
    const usage = response.usage
      ? {
          inputTokens: response.usage.prompt_tokens || 0,
          outputTokens: response.usage.completion_tokens || 0,
        }
      : undefined;

    // Use the actual model identifier from the API response
    const actualModelId = response.model || modelId;

    return {
      providerId: this.id,
      modelId: actualModelId,
      usage,
      output: {
        messages: [{ role: "assistant", content }],
        raw: response,
      },
    };
  },
};

