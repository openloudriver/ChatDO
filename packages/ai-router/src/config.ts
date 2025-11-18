import { AiIntent, CostTier } from "./types";

export interface RoutingRule {
  intent: AiIntent;
  defaultProviderId: string;
  cheapFallbackId?: string;
  strictPrivacyOnlyIds?: string[]; // e.g. local-only
}

export const routingRules: RoutingRule[] = [
  {
    intent: "long_planning",
    defaultProviderId: "openai-gpt5",
    cheapFallbackId: "mistral-large",
  },
  {
    intent: "code_gen",
    defaultProviderId: "grok-code",
    cheapFallbackId: "deepseek-coder",
  },
  {
    intent: "code_edit",
    defaultProviderId: "grok-code",
    cheapFallbackId: "deepseek-coder",
  },
  {
    intent: "doc_draft",
    defaultProviderId: "anthropic-claude-sonnet",
    cheapFallbackId: "mistral-large",
  },
  {
    intent: "general_chat",
    defaultProviderId: "openai-gpt5",
    cheapFallbackId: "mistral-large",
  },
  {
    intent: "review",
    defaultProviderId: "anthropic-claude-sonnet",
    cheapFallbackId: "mistral-large",
  },
  {
    intent: "summarize",
    defaultProviderId: "anthropic-claude-sonnet",
    cheapFallbackId: "mistral-large",
  },
  {
    intent: "tool_orchestration",
    defaultProviderId: "openai-gpt5",
    cheapFallbackId: "mistral-large",
  },
];

