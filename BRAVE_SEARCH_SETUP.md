# Brave Search API Setup for ChatDO

ChatDO now supports Brave Search API for better, more reliable web search results (just like you use in Brave Browser!).

## Why Brave Search?

- **Better Results**: Same search engine you use in Brave Browser
- **No Canva Issues**: Proper API results, not random redirects
- **Recent Results**: Can prioritize fresh content
- **Privacy-Focused**: Brave's independent search index

## Setup Instructions

### 1. Get Your Brave Search API Key

1. Go to [Brave Search API](https://brave.com/search/api/)
2. Sign up for a free account (or paid if you need more queries)
3. Get your API key from the dashboard

### 2. Add API Key to Environment

**Option 1: Using .env file (Recommended)**

Create a `.env` file in the ChatDO root directory (same level as `server/`, `web/`, etc.):

```bash
cd /Users/christopher.peck/ChatDO
nano .env
```

Add this line:
```bash
BRAVE_SEARCH_API_KEY=your-api-key-here
```

Save and close. The server will automatically load it on startup.

**Option 2: Export in your shell**

If you prefer to export it in your terminal session:

```bash
export BRAVE_SEARCH_API_KEY=your-api-key-here
```

**Note**: The `.env` file method is recommended because it persists across sessions.

### 3. Restart ChatDO Server

After adding the API key, restart the FastAPI server:

```bash
cd server
python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## How It Works

- **Brave Search API Required**: ChatDO uses Brave Search API exclusively (same as Brave Browser)
- **No Fallback**: DuckDuckGo has been removed. You must set BRAVE_SEARCH_API_KEY for web search to work.

## Pricing

- **Free Tier**: 2,000 queries/month
- **Paid Plans**: Available for higher usage

## Notes

- Brave Search API provides the same results you see in Brave Browser
- Accurate, reliable results - no more Canva redirects or weird results!
- **Required**: You must set BRAVE_SEARCH_API_KEY for web search to work
- ChatDO will show a clear error message if the API key is missing

