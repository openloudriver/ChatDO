import { AiIntent } from "./types";

// Model routing: summarize_article uses GPT-5, web_search uses Brave Search API (handled before routing), others use gpt-5
export const routingRules: Record<AiIntent, { model: string; providerId: string }> = {
  long_planning: { model: "gpt-5", providerId: "openai-gpt5" },
  general_chat: { model: "gpt-5", providerId: "openai-gpt5" },
  summarize: { model: "gpt-5", providerId: "openai-gpt5" },  // GPT-5 for summaries
  summarize_article: { model: "gpt-5", providerId: "openai-gpt5" },  // GPT-5 for article summaries
  file_summary: { model: "gpt-5", providerId: "openai-gpt5" },  // GPT-5 for file/document summaries
  doc_draft: { model: "gpt-5", providerId: "openai-gpt5" },
  code_gen: { model: "gpt-5", providerId: "openai-gpt5" },
  code_edit: { model: "gpt-5", providerId: "openai-gpt5" },
  review: { model: "gpt-5", providerId: "openai-gpt5" },
  tool_orchestration: { model: "gpt-5", providerId: "openai-gpt5" },
  web_search: { model: "gpt-5", providerId: "openai-gpt5" },  // NOTE: Not actually used - web_search is handled before routing, returns structured results from Brave Search API
};

