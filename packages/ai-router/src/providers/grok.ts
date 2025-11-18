import { AiProvider, AiRouterInput, AiRouterResult } from "../types";

export const grokCodeProvider: AiProvider = {
  id: "grok-code",
  label: "Grok Code",
  costTier: "standard",
  maxContextTokens: 128_000,
  specialties: [
    "code_gen",
    "code_edit",
    "review",
  ],
  supportsPrivacyLevel(level) {
    return level === "normal";
  },
  async invoke(input: AiRouterInput): Promise<AiRouterResult> {
    // TODO: wire to actual Grok API
    const modelId = "grok-2-code";
    const fakeContent = `[grok-code stub] intent=${input.intent}`;
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

