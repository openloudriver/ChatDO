import OpenAI from "openai";
import {
  AiProvider,
  AiRouterInput,
  AiRouterResult,
} from "../types";

const client = new OpenAI({
  apiKey: process.env.GAB_AI_API_KEY,
  baseURL: process.env.GAB_AI_BASE_URL || "https://gab.ai/v1",
  timeout: 60000, // 60 seconds timeout for Gab AI (scraping can take longer)
});

export const gabAiProvider: AiProvider = {
  id: "gab-ai",
  label: "Gab AI",
  costTier: "standard",
  maxContextTokens: 128_000, // Typical for OpenAI-compatible APIs
  specialties: [
    "web_scraping",
    "general_chat",
    "summarize",
    "doc_draft",
  ],

  supportsPrivacyLevel(level) {
    return level === "normal"; // Gab AI is external, so only normal privacy
  },

  async invoke(input: AiRouterInput): Promise<AiRouterResult> {
    if (!process.env.GAB_AI_API_KEY) {
      throw new Error("GAB_AI_API_KEY environment variable is not set");
    }

    const messages = input.input.messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    // Get model from routing rules or default to "arya"
    // Can be overridden via systemHint
    const modelId = (input.input.systemHint as string) || "arya";

    const response = await client.chat.completions.create({
      model: modelId,
      messages,
    });

    const content =
      response.choices[0]?.message?.content ?? "[gab-ai] empty response";

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

