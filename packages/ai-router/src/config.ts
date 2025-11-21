import { AiIntent } from "./types";

// Model routing: web_scraping and web_search use Gab AI, others use gpt-5
export const routingRules: Record<AiIntent, { model: string; providerId: string }> = {
  long_planning: { model: "gpt-5", providerId: "openai-gpt5" },
  general_chat: { model: "gpt-5", providerId: "openai-gpt5" },
  summarize: { model: "gpt-5", providerId: "openai-gpt5" },
  doc_draft: { model: "gpt-5", providerId: "openai-gpt5" },
  code_gen: { model: "gpt-5", providerId: "openai-gpt5" },
  code_edit: { model: "gpt-5", providerId: "openai-gpt5" },
  review: { model: "gpt-5", providerId: "openai-gpt5" },
  tool_orchestration: { model: "gpt-5", providerId: "openai-gpt5" },
  web_scraping: { model: "arya", providerId: "gab-ai" },
  web_search: { model: "arya", providerId: "gab-ai" },
};

