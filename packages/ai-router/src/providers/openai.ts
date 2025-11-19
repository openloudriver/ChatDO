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

    // gpt-5-codex requires v1/responses endpoint, not v1/chat/completions
    if (modelId.includes("codex")) {
      // Use responses API for codex models
      const response = await fetch(`${process.env.OPENAI_BASE_URL || "https://api.openai.com/v1"}/responses`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${process.env.OPENAI_API_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: modelId,
          input: messages,
        }),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ error: { message: "Unknown error" } }));
        throw new Error(`OpenAI API error: ${error.error?.message || response.statusText}`);
      }

      const data = await response.json();
      const content = data.output?.[0]?.content?.[0]?.text || data.output?.[0]?.text || "[openai-gpt5-codex] empty response";
      
      return {
        providerId: this.id,
        modelId: data.model || modelId,
        usage: data.usage ? {
          inputTokens: data.usage.input_tokens || 0,
          outputTokens: data.usage.output_tokens || 0,
        } : undefined,
        output: {
          messages: [{ role: "assistant", content }],
          raw: data,
        },
      };
    }

    // Regular chat completions for gpt-5
    // gpt-5 models don't support custom temperature - only default (1)
    const requestParams: any = {
      model: modelId,
      messages,
    };
    
    // Only add temperature for models that support it (not gpt-5 models)
    if (!modelId.startsWith("gpt-5")) {
      requestParams.temperature = 0.4;
    }

    const response = await client.chat.completions.create(requestParams);

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

