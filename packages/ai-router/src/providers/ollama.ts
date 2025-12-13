import {
  AiProvider,
  AiRouterInput,
  AiRouterResult,
} from "../types";

const OLLAMA_BASE_URL = process.env.OLLAMA_BASE_URL || "http://localhost:11434";

export const ollamaLlamaProvider: AiProvider = {
  id: "ollama-llama",
  label: "Ollama Llama 3.2 3B",
  costTier: "cheap",
  maxContextTokens: 32_000,
  specialties: [
    "general_chat", // Memory queries will use this
  ],

  supportsPrivacyLevel(level) {
    // Ollama runs locally, so it supports strict privacy
    return level === "normal" || level === "strict";
  },

  async invoke(input: AiRouterInput): Promise<AiRouterResult> {
    // Map messages to Ollama format
    const messages = input.input.messages.map((m: any) => ({
      role: m.role === "system" ? "system" : m.role === "assistant" ? "assistant" : "user",
      content: m.content || "",
    }));

    // Get model from systemHint or default to llama3.2:3b
    const modelId = (input.input.systemHint as string) || "llama3.2:3b";

    // Ollama API endpoint
    const url = `${OLLAMA_BASE_URL}/api/chat`;

    const requestPayload = {
      model: modelId,
      messages,
      stream: false,
      options: {
        temperature: 0.7,
        top_p: 0.9,
      },
    };

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestPayload),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Ollama API error: ${response.status} ${errorText}`);
      }

      const data = await response.json();

      // Ollama response format: { message: { content: "...", role: "assistant" }, ... }
      const content = data.message?.content ?? "[ollama-llama] empty response";

      // Ollama doesn't provide token usage by default, but we can estimate
      // Rough estimate: ~4 chars per token
      const estimatedInputTokens = Math.ceil(
        messages.reduce((sum, m) => sum + (m.content?.length || 0), 0) / 4
      );
      const estimatedOutputTokens = Math.ceil(content.length / 4);

      const usage = {
        inputTokens: estimatedInputTokens,
        outputTokens: estimatedOutputTokens,
      };

      return {
        providerId: this.id,
        modelId: modelId,
        usage,
        output: {
          messages: [
            {
              role: "assistant",
              content,
            },
          ],
          raw: data,
        },
      };
    } catch (error: any) {
      throw new Error(`Ollama provider error: ${error.message}`);
    }
  },
};
