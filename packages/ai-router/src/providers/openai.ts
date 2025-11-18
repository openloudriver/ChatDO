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

const MODEL_ID = process.env.OPENAI_MODEL_GPT5 || "gpt-5.1";

export const openAiGpt5Provider: AiProvider = {
  id: "openai-gpt5",
  label: "OpenAI GPT-5.1",
  costTier: "premium",
  maxContextTokens: 200_000,
  specialties: [
    "long_planning",
    "general_chat",
    "doc_draft",
    "tool_orchestration",
    "code_edit",
  ],

  supportsPrivacyLevel(level) {
    // later you can make strict do something special, like extra redaction
    return level === "normal" || level === "strict";
  },

  async invoke(input: AiRouterInput): Promise<AiRouterResult> {
    const messages = input.input.messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const response = await client.chat.completions.create({
      model: MODEL_ID,
      messages,
      // TODO: map tools if/when you're ready
      temperature: 0.4,
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

    return {
      providerId: this.id,
      modelId: MODEL_ID,
      usage,
      output: {
        messages: [{ role: "assistant", content }],
        raw: response,
      },
    };
  },
};

