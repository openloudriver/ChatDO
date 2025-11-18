import { AiProvider, AiRouterInput, AiRouterResult } from "../types";

export const llamaLocalProvider: AiProvider = {
  id: "llama-local",
  label: "Llama Local (On-Prem)",
  costTier: "cheap",
  maxContextTokens: 32_000,
  specialties: [
    "general_chat",
    "summarize",
    "doc_draft",
  ],
  supportsPrivacyLevel(level) {
    // Local models support strict privacy
    return level === "strict" || level === "normal";
  },
  async invoke(input: AiRouterInput): Promise<AiRouterResult> {
    // TODO: wire to local Llama inference server
    const modelId = "llama-3.1-70b";
    const fakeContent = `[llama-local stub] intent=${input.intent}`;
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

