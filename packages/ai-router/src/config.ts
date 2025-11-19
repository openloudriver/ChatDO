import { AiIntent } from "./types";

// Model routing: map intents to OpenAI models (gpt-5 or gpt-5-codex)
export const routingRules: Record<AiIntent, { model: string; providerId: string }> = {
  long_planning: { model: "gpt-5", providerId: "openai-gpt5" },
  general_chat: { model: "gpt-5", providerId: "openai-gpt5" },
  summarize: { model: "gpt-5", providerId: "openai-gpt5" },
  doc_draft: { model: "gpt-5", providerId: "openai-gpt5" },
  code_gen: { model: "gpt-5-codex", providerId: "openai-gpt5" },
  code_edit: { model: "gpt-5-codex", providerId: "openai-gpt5" },
  review: { model: "gpt-5", providerId: "openai-gpt5" },
  tool_orchestration: { model: "gpt-5", providerId: "openai-gpt5" },
};

