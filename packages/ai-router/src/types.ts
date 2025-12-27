// High-level "task" ChatDO is asking for.
// NOTE: librarian intent removed - Memory Service is now a tool only, GPT-5 always generates responses
export type AiIntent =
  | "general_chat"
  | "long_planning"
  | "code_gen"
  | "code_edit"
  | "review"
  | "doc_draft"
  | "summarize"
  | "summarize_article"
  | "file_summary"
  | "tool_orchestration"
  | "web_search"
  | "nano_routing"
  | "nano_facts";

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
    tools?: any[];        // OpenAI-style tool definitions
    tool_choice?: any;    // optional tool_choice parameter (e.g., "auto", "none", or specific tool)
    systemHint?: string;  // optional routing hint
    temperature?: number; // optional temperature (0.0-2.0)
    response_format?: any; // optional response format (e.g., JSON schema)
  };
}

export interface AiUsage {
  inputTokens: number;
  outputTokens: number;
}

export interface AiRouterResult {
  providerId: string;
  modelId: string;
  usage?: AiUsage; // optional: some providers may not return usage yet
  output: {
    messages: Array<{ 
      role: "assistant"; 
      content: string;
      tool_calls?: any[]; // OpenAI-style tool_calls array (preserved from provider response)
    }>;
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

