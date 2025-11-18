import { AiProvider, AiRouterInput, AiRouterResult } from "../types";

export const mistralLargeProvider: AiProvider = {
  id: "mistral-large",
  label: "Mistral Large",
  costTier: "cheap",
  maxContextTokens: 128_000,
  specialties: [
    "general_chat",
    "doc_draft",
    "summarize",
    "long_planning",
  ],
  supportsPrivacyLevel(level) {
    return level === "normal";
  },
  async invoke(input: AiRouterInput): Promise<AiRouterResult> {
    // TODO: wire to actual Mistral API
    const modelId = "mistral-large-2";
    const fakeContent = `[mistral-large stub] intent=${input.intent}`;
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

