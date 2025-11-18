# AI-Router (ai-router)

> Single entrypoint for all external and local AI models used by ChatDO, Keeper, and Mesh.

## Purpose

- Provide a unified interface for ChatDO to call any AI model.
- Centralize routing, policy enforcement, and provider selection.
- Enable model redundancy, specialization, and vendor-agnostic behavior.

## Guarantees

- ChatDO never calls provider APIs directly.
- All provider usage is governed by routing + policy config.
- Providers are pluggable; adding/removing a model doesn't affect callers.
- State (memory, logs) lives *outside* providers; models remain stateless.

## High-Level API

```ts
import { runTask } from "@privacypay/ai-router";

const result = await runTask({
  role: "chatdo",
  intent: "code_edit" | "long_planning" | "quick_reply" | "doc_draft",
  priority: "low" | "medium" | "high",
  privacyLevel: "strict" | "normal",
  costTier: "cheap" | "standard" | "premium",
  input: {
    messages: [...],
    tools: [...],        // optional tool definitions
    systemHint: "..."    // optional extra routing hint
  }
});
```

## Providers

Each provider implements a common interface:

- `id`: unique string ("openai-gpt5", "anthropic-claude", etc.)
- `supports`: capabilities (code, long_context, cheap_batches, etc.)
- `invoke()`: make the actual API call.

Routing is config-driven and can be evolved without changing callers.

## Usage Example

```ts
import { runTask, AiIntent } from "@privacypay/ai-router";

async function chatDoHandleRequest(userMessages: any[]) {
  // Your own logic to classify intent, set privacy, etc.
  const intent: AiIntent = "long_planning";
  
  const result = await runTask({
    role: "chatdo",
    intent,
    priority: "high",
    privacyLevel: "normal",
    costTier: "standard",
    input: {
      messages: userMessages,
      systemHint: "ChatDO core request",
    },
  });
  
  return result.output.messages;
}
```

## Architecture

- **types.ts**: Core interfaces and types
- **config.ts**: Routing rules and provider selection logic
- **router.ts**: Main routing function that selects and invokes providers
- **providers/**: Individual provider implementations (OpenAI, Anthropic, Grok, etc.)

## Adding New Providers

1. Create a new file in `src/providers/` (e.g., `deepseek.ts`)
2. Implement the `AiProvider` interface
3. Register the provider in `router.ts`
4. Add routing rules in `config.ts` if needed

