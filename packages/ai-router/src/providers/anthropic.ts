import { AiProvider, AiRouterInput, AiRouterResult } from "../types";

export const claudeSonnetProvider: AiProvider = {
  id: "anthropic-claude-sonnet",
  label: "Anthropic Claude Sonnet",
  costTier: "premium",
  maxContextTokens: 200_000,
  specialties: [
    "doc_draft",
    "review",
    "summarize",
    "long_planning",
  ],
  supportsPrivacyLevel(level) {
    return level === "normal" || level === "strict";
  },
  async invoke(input: AiRouterInput): Promise<AiRouterResult> {
    // TODO: wire to actual Anthropic client
    const modelId = "claude-sonnet-4";
    const fakeContent = `[anthropic-claude-sonnet stub] intent=${input.intent}`;
    return {
      providerId: this.id,
      modelId,
      output: {
        messages: [{ role: "assistant", content: fakeContent }],
        raw: null,
      },
    };
  },
};

