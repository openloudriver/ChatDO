// High-level "task" ChatDO is asking for.
export type AiIntent =
  | "general_chat"
  | "long_planning"
  | "code_gen"
  | "code_edit"
  | "review"
  | "doc_draft"
  | "summarize"
  | "tool_orchestration";

export type Priority = "low" | "medium" | "high";

export type PrivacyLevel = "strict" | "normal";

export type CostTier = "cheap" | "standard" | "premium";

export interface AiRouterInput {
  role: "chatdo" | "keeper" | "mesh-node" | "system";
  intent: AiIntent;
  priority: Priority;
  privacyLevel: PrivacyLevel;
  costTier: CostTier;
  input: {
    messages: Array<{ role: "system" | "user" | "assistant"; content: string }>;
    tools?: any[];        // refine later for your tool schema
    systemHint?: string;  // optional routing hint
  };
}

export interface AiRouterResult {
  providerId: string;
  modelId: string;
  output: {
    messages: Array<{ role: "assistant"; content: string }>;
    raw?: any; // raw provider response if you want it
  };
}

// What every provider module must implement:
export interface AiProvider {
  id: string; // "openai-gpt5", "anthropic-claude-sonnet", etc.
  label: string;
  costTier: CostTier;
  maxContextTokens: number;
  specialties: AiIntent[];
  supportsPrivacyLevel(level: PrivacyLevel): boolean;
  invoke(input: AiRouterInput): Promise<AiRouterResult>;
}

