import { AiProvider, AiRouterInput, AiRouterResult } from "../types";

const OLLAMA_BASE_URL = process.env.OLLAMA_BASE_URL || "http://localhost:11434";
const OLLAMA_SUMMARY_MODEL = process.env.OLLAMA_SUMMARY_MODEL || "llama3.1:8b";

interface OllamaMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

interface OllamaChatRequest {
  model: string;
  messages: OllamaMessage[];
  stream?: boolean;
}

interface OllamaChatResponse {
  message: {
    role: string;
    content: string;
  };
  done: boolean;
  total_duration?: number;
  load_duration?: number;
  prompt_eval_count?: number;
  prompt_eval_duration?: number;
  eval_count?: number;
  eval_duration?: number;
}

async function callOllama(
  modelName: string,
  messages: OllamaMessage[],
): Promise<string> {
  const url = `${OLLAMA_BASE_URL}/api/chat`;
  const payload: OllamaChatRequest = {
    model: modelName,
    messages,
    stream: false,
  };

  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(
      `Ollama API error (${response.status}): ${errorText}`,
    );
  }

  const data: OllamaChatResponse = await response.json();
  return data.message.content || "";
}

export const ollamaProvider: AiProvider = {
  id: "ollama-local",
  label: "Ollama Local",
  costTier: "cheap",
  maxContextTokens: 32_000,
  specialties: ["summarize", "general_chat"],
  supportsPrivacyLevel(level) {
    // Local models support strict privacy
    return level === "strict" || level === "normal";
  },
  async invoke(input: AiRouterInput): Promise<AiRouterResult> {
    const modelId =
      (input.input.systemHint as string) || OLLAMA_SUMMARY_MODEL;

    // Convert messages to Ollama format
    const ollamaMessages: OllamaMessage[] = input.input.messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const content = await callOllama(modelId, ollamaMessages);

    // Ollama doesn't provide token usage in the same way, so we estimate
    // For now, we'll skip usage tracking for Ollama (it's free/local)
    return {
      providerId: this.id,
      modelId,
      output: {
        messages: [{ role: "assistant", content }],
        raw: null,
      },
    };
  },
};

// Helper function for direct Ollama calls (e.g., from Python backend)
export async function callOllamaSummary(
  systemPrompt: string,
  userPrompt: string,
): Promise<string> {
  const messages: OllamaMessage[] = [
    { role: "system", content: systemPrompt },
    { role: "user", content: userPrompt },
  ];
  return await callOllama(OLLAMA_SUMMARY_MODEL, messages);
}

