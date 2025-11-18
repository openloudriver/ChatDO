import { AiRouterInput, AiRouterResult, AiProvider } from "./types";
import { routingRules } from "./config";
import { openAiGpt5Provider } from "./providers/openai";
import { claudeSonnetProvider } from "./providers/anthropic";
import { grokCodeProvider } from "./providers/grok";
import { geminiProProvider } from "./providers/gemini";
import { mistralLargeProvider } from "./providers/mistral";
import { llamaLocalProvider } from "./providers/llamaLocal";

const providers: Record<string, AiProvider> = {
  [openAiGpt5Provider.id]: openAiGpt5Provider,
  [claudeSonnetProvider.id]: claudeSonnetProvider,
  [grokCodeProvider.id]: grokCodeProvider,
  [geminiProProvider.id]: geminiProProvider,
  [mistralLargeProvider.id]: mistralLargeProvider,
  [llamaLocalProvider.id]: llamaLocalProvider,
};

function selectProvider(input: AiRouterInput): AiProvider {
  const rule = routingRules.find((r) => r.intent === input.intent);
  // Default: fallback to GPT-5 if no specific rule
  const defaultId = rule?.defaultProviderId ?? "openai-gpt5";
  let candidate = providers[defaultId];

  // Adjust for cost-tier
  if (input.costTier === "cheap" && rule?.cheapFallbackId) {
    candidate = providers[rule.cheapFallbackId] ?? candidate;
  }

  // Adjust for strict privacy (e.g. local only)
  if (input.privacyLevel === "strict") {
    // Simple version: prefer local model if available
    const local = providers["llama-local"];
    if (local && local.supportsPrivacyLevel("strict")) {
      candidate = local;
    }
  }

  if (!candidate) {
    throw new Error("No suitable provider found for AI-Router.");
  }

  if (!candidate.supportsPrivacyLevel(input.privacyLevel)) {
    throw new Error(
      `Selected provider ${candidate.id} does not support privacy level ${input.privacyLevel}`,
    );
  }

  return candidate;
}

export async function runTask(input: AiRouterInput): Promise<AiRouterResult> {
  const provider = selectProvider(input);
  return provider.invoke(input);
}

