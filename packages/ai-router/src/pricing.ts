export interface PricingEntry {
  providerId: string; // "openai-gpt5", "anthropic-claude-sonnet", etc.
  inputPerMillion: number; // USD
  cachedInputPerMillion?: number; // USD (optional, for cached input tokens)
  outputPerMillion: number; // USD
}

export const PRICING: PricingEntry[] = [
  {
    providerId: "openai-gpt5",
    // Verified pricing as of November 2025: $1.25 per million input tokens, $10.00 per million output tokens
    inputPerMillion: 1.25,
    outputPerMillion: 10.0,
  },
  {
    providerId: "openai-gpt5-mini",
    // GPT-5 Mini pricing: $0.25 per million input tokens, $0.025 per million cached input tokens, $2.00 per million output tokens
    inputPerMillion: 0.25,
    cachedInputPerMillion: 0.025,
    outputPerMillion: 2.0,
  },
  {
    providerId: "anthropic-claude-sonnet",
    inputPerMillion: 3.0,
    outputPerMillion: 15.0,
  },
  {
    providerId: "grok-code",
    inputPerMillion: 2.0,
    outputPerMillion: 8.0,
  },
  {
    providerId: "gemini-pro",
    inputPerMillion: 1.1,
    outputPerMillion: 4.4,
  },
  {
    providerId: "mistral-large",
    inputPerMillion: 3.0,
    outputPerMillion: 15.0,
  },
];

export function findPricing(providerId: string): PricingEntry | null {
  return PRICING.find((p) => p.providerId === providerId) ?? null;
}

