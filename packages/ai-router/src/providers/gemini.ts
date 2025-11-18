import { AiProvider, AiRouterInput, AiRouterResult } from "../types";

export const geminiProProvider: AiProvider = {
  id: "gemini-pro",
  label: "Google Gemini Pro",
  costTier: "standard",
  maxContextTokens: 1_000_000,
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
    // TODO: wire to actual Gemini API
    const modelId = "gemini-2.0-pro";
    const fakeContent = `[gemini-pro stub] intent=${input.intent}`;
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

