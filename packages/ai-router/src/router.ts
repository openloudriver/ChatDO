import { AiRouterInput, AiRouterResult, AiProvider } from "./types";
import { routingRules } from "./config";
import { findPricing } from "./pricing";
import { recordUsage } from "./spendTracker";
import { openAiGpt5Provider } from "./providers/openai";
import { claudeSonnetProvider } from "./providers/anthropic";
import { grokCodeProvider } from "./providers/grok";
import { geminiProProvider } from "./providers/gemini";
import { mistralLargeProvider } from "./providers/mistral";
import { llamaLocalProvider } from "./providers/llamaLocal";
import { gabAiProvider } from "./providers/gabai";

const providers: Record<string, AiProvider> = {
  [openAiGpt5Provider.id]: openAiGpt5Provider,
  [claudeSonnetProvider.id]: claudeSonnetProvider,
  [grokCodeProvider.id]: grokCodeProvider,
  [geminiProProvider.id]: geminiProProvider,
  [mistralLargeProvider.id]: mistralLargeProvider,
  [llamaLocalProvider.id]: llamaLocalProvider,
  [gabAiProvider.id]: gabAiProvider,
};

function selectProvider(input: AiRouterInput): { provider: AiProvider; model: string } {
  // Handle strict privacy - use local model
  if (input.privacyLevel === "strict") {
    const local = providers["llama-local"];
    if (local && local.supportsPrivacyLevel("strict")) {
      return { provider: local, model: "llama-local" };
    }
  }

  // Get routing rule for this intent
  const rule = routingRules[input.intent];
  if (!rule) {
    throw new Error(`No routing rule found for intent: ${input.intent}`);
  }

  const provider = providers[rule.providerId];
  if (!provider) {
    throw new Error(`Provider not found: ${rule.providerId}`);
  }

  if (!provider.supportsPrivacyLevel(input.privacyLevel)) {
    throw new Error(
      `Provider ${provider.id} does not support privacy level ${input.privacyLevel}`,
    );
  }

  return { provider, model: rule.model };
}

export async function runTask(input: AiRouterInput): Promise<AiRouterResult> {
  const { provider, model } = selectProvider(input);
  
  // Pass model selection to provider via systemHint
  const inputWithModel = {
    ...input,
    input: {
      ...input.input,
      systemHint: model,
    },
  };

  const start = Date.now();
  const result = await provider.invoke(inputWithModel);
  const ms = Date.now() - start;

  console.log(
    `[AI-Router] intent=${input.intent} provider=${result.providerId} model=${result.modelId} ms=${ms}`,
  );

  // Cost tracking
  if (result.usage) {
    const pricing = findPricing(result.providerId);
    if (pricing) {
      const { inputTokens, outputTokens } = result.usage;
      const costUsd =
        (inputTokens / 1_000_000) * pricing.inputPerMillion +
        (outputTokens / 1_000_000) * pricing.outputPerMillion;

      await recordUsage(result.providerId, result.modelId, costUsd);
      console.log(`[AI-Router] Recorded usage: provider=${result.providerId} cost=$${costUsd.toFixed(6)}`);
    } else {
      console.warn(`[AI-Router] No pricing found for provider: ${result.providerId}`);
    }
  } else {
    console.warn(`[AI-Router] No usage data returned from provider: ${result.providerId}`);
  }

  return result;
}


