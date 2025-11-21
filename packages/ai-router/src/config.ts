import { AiIntent } from "./types";

// Model routing: web_scraping uses Gab AI, web_search uses GPT-5, others use gpt-5
export const routingRules: Record<AiIntent, { model: string; providerId: string }> = {
  long_planning: { model: "gpt-5", providerId: "openai-gpt5" },
  general_chat: { model: "gpt-5", providerId: "openai-gpt5" },
  summarize: { model: "llama3.1:8b", providerId: "ollama-local" },  // Ollama for summaries
  doc_draft: { model: "gpt-5", providerId: "openai-gpt5" },
  code_gen: { model: "gpt-5", providerId: "openai-gpt5" },
  code_edit: { model: "gpt-5", providerId: "openai-gpt5" },
  review: { model: "gpt-5", providerId: "openai-gpt5" },
  tool_orchestration: { model: "gpt-5", providerId: "openai-gpt5" },
  web_scraping: { model: "arya", providerId: "gab-ai" },  // Gab AI for scraping specific URLs
  web_search: { model: "gpt-5", providerId: "openai-gpt5" },  // NOTE: Not actually used - web_search is handled before routing, returns structured results from Brave Search API
};

