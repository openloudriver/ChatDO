import { AiProvider, AiRouterInput, AiRouterResult } from "../types";

export const openAiGpt5Provider: AiProvider = {
  id: "openai-gpt5",
  label: "OpenAI GPT-5.1",
  costTier: "premium",
  maxContextTokens: 200_000,
  specialties: [
    "long_planning",
    "general_chat",
    "doc_draft",
    "tool_orchestration",
    "code_edit",
  ],
  supportsPrivacyLevel(level) {
    // for now: allow both, later you can block strict if needed
    return level === "normal" || level === "strict";
  },
  async invoke(input: AiRouterInput): Promise<AiRouterResult> {
    // TODO: wire to actual OpenAI client
    // This is where you'd map AiRouterInput -> OpenAI chat.completions.create
    const modelId = "gpt-5.1";
    // placeholder stub so Cursor has a structure
    const fakeContent = `[openai-gpt5 stub] intent=${input.intent}`;
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

