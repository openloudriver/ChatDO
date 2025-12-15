import OpenAI from "openai";
import {
  AiProvider,
  AiRouterInput,
  AiRouterResult,
} from "../types";

const client = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
  baseURL: process.env.OPENAI_BASE_URL || "https://api.openai.com/v1",
  timeout: 120000, // 120 seconds for complex reasoning queries
});

export const openAiGpt5NanoProvider: AiProvider = {
  id: "openai-gpt5-nano",
  label: "GPT-5 Nano",
  costTier: "cheap",
  maxContextTokens: 200_000,
  specialties: [
    // No specialties - librarian intent removed
  ],

  supportsPrivacyLevel(level) {
    return level === "normal" || level === "strict";
  },

  async invoke(input: AiRouterInput): Promise<AiRouterResult> {
    // Map messages, preserving tool_calls and tool_call_id for tool messages
    const messages = input.input.messages.map((m: any) => {
      const message: any = {
        role: m.role,
        content: m.content || "",
      };
      // Preserve tool_calls if present (for assistant messages)
      if (m.tool_calls) {
        message.tool_calls = m.tool_calls;
      }
      // Preserve tool_call_id if present (for tool role messages)
      if (m.tool_call_id) {
        message.tool_call_id = m.tool_call_id;
      }
      // Preserve name if present (for tool role messages)
      if (m.name) {
        message.name = m.name;
      }
      return message;
    });

    // Get model from routing rules (passed via systemHint or determined by intent)
    // Default to gpt-5-nano if not specified
    const modelId = (input.input.systemHint as string) || "gpt-5-nano";

    // Sanity check: only gpt-5-nano is allowed
    if (modelId !== "gpt-5-nano") {
      throw new Error(
        `Invalid model: ${modelId}. This provider only supports gpt-5-nano.`
      );
    }

    // Extract tools and tool_choice from input (if provided)
    const { tools, tool_choice } = input.input;

    // Build request payload - conditionally include tools and tool_choice
    const requestPayload: any = {
      model: modelId,
      messages,
    };

    // Add tools if provided (backwards-compatible: only add if present)
    if (tools) {
      requestPayload.tools = tools;
    }

    // Add tool_choice if provided (backwards-compatible: only add if present)
    if (tool_choice !== undefined) {
      requestPayload.tool_choice = tool_choice;
    }

    // gpt-5-nano uses v1/chat/completions endpoint
    // gpt-5-nano models don't support custom temperature - only default (1)
    const response = await client.chat.completions.create(requestPayload);

    // Get the assistant message from OpenAI response
    const assistantMessage = response.choices[0]?.message;
    const content = assistantMessage?.content ?? "[openai-gpt5-nano] empty response";
    
    // Preserve tool_calls if present (for tool loop in Python)
    const tool_calls = assistantMessage?.tool_calls;

    // Extract usage information
    const usage = response.usage
      ? {
          inputTokens: response.usage.prompt_tokens || 0,
          outputTokens: response.usage.completion_tokens || 0,
        }
      : undefined;

    // Use the actual model identifier from the API response
    const actualModelId = response.model || modelId;

    // Build response message with optional tool_calls
    const responseMessage: any = {
      role: "assistant" as const,
      content,
    };
    if (tool_calls) {
      responseMessage.tool_calls = tool_calls;
    }

    return {
      providerId: this.id,
      modelId: actualModelId,
      usage,
      output: {
        messages: [responseMessage],
        raw: response,
      },
    };
  },
};
