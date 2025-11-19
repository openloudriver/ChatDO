# Testing AI-Router

## Start the Server

```bash
cd packages/ai-router
pnpm dev
```

The server will start on `http://localhost:8081` (or the port specified in `AI_ROUTER_PORT` env var).

## Test with curl

```bash
curl -X POST http://localhost:8081/v1/ai/run \
  -H "Content-Type: application/json" \
  -d '{
    "role": "chatdo",
    "intent": "general_chat",
    "priority": "high",
    "privacyLevel": "normal",
    "costTier": "standard",
    "input": {
      "messages": [
        { "role": "user", "content": "Hello" }
      ]
    }
  }'
```

## Expected Response

```json
{
  "ok": true,
  "providerId": "openai-gpt5",
  "modelId": "gpt-5",
  "output": {
    "messages": [
      {
        "role": "assistant",
        "content": "Hello! This is GPT-5 responding through the AI-Router..."
      }
    ]
  }
}
```

## Environment Variables

Make sure you have a `.env` file (or export env vars) with:

```bash
OPENAI_API_KEY=your-actual-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
AI_ROUTER_PORT=8081
```

Note: All intents use gpt-5. Model selection is handled automatically by routing rules.

