# ChatDO v1.5 Setup Instructions

ChatDO v1.5 adds a ChatGPT-style web UI with FastAPI backend.

## Prerequisites

- Python 3.10+
- Node.js 18+ and pnpm
- ChatDO v1.0 already set up (with virtual environment)

## Backend Setup (FastAPI Server)

1. **Install server dependencies:**

```bash
cd /Users/christopher.peck/ChatDO
source .venv/bin/activate  # if not already activated
pip install fastapi uvicorn[standard] python-multipart aiofiles httpx
pip install PyPDF2 pdfplumber python-docx  # Optional: for file extraction
pip install trafilatura readability-lxml beautifulsoup4  # Optional: for URL scraping
pip install ddgs  # For web search (DuckDuckGo fallback)
```

2. **Configure Brave Search API (Required for Web Search)**

ChatDO uses Brave Search API exclusively for web search (same search engine as Brave Browser). Get your API key from [Brave Search API](https://brave.com/search/api/) and add it to your environment:

```bash
export BRAVE_SEARCH_API_KEY=your-api-key-here
```

Or add it to a `.env` file in the ChatDO root directory. See `BRAVE_SEARCH_SETUP.md` for detailed instructions.

**Note**: Web search will not work without a valid BRAVE_SEARCH_API_KEY.

2. **Start the FastAPI server:**

```bash
cd server
uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
```

The server will be available at `http://localhost:8000`

## Frontend Setup (React Web UI)

1. **Install dependencies:**

```bash
cd /Users/christopher.peck/ChatDO/web
pnpm install
```

2. **Start the development server:**

```bash
pnpm dev
```

The web app will be available at `http://localhost:5173`

## Usage

1. **Start the backend first:**
   ```bash
   cd server
   uvicorn server.main:app --reload
   ```

2. **Then start the frontend:**
   ```bash
   cd web
   pnpm dev
   ```

3. **Open your browser:**
   Navigate to `http://localhost:5173`

## Features

- **Text Chat**: Send messages to ChatDO
- **Persistent Threads**: Conversations are saved and can be resumed
- **Project Selection**: Switch between different projects (PrivacyPay, DRR, etc.)
- **File Upload**: Upload files (PDF, Word, images) - text extraction coming soon
- **URL Scraping**: Scrape web pages and add to conversation context
- **Streaming**: Real-time streaming responses via WebSocket (with REST fallback)
- **Chat Trash System**: Soft-delete chats with automatic retention and cleanup

## API Endpoints

- `GET /api/projects` - List available projects
- `POST /api/projects` - Create a new project
- `PATCH /api/projects/{id}` - Update a project
- `DELETE /api/projects/{id}` - Delete a project
- `GET /api/chats` - List chats (with optional `project_id` and `include_trashed` params)
- `POST /api/new_conversation` - Create a new conversation thread
- `DELETE /api/chats/{id}` - Soft delete a chat (move to trash)
- `POST /api/chats/{id}/restore` - Restore a chat from trash
- `POST /api/chats/{id}/purge` - Permanently delete a chat and its history
- `POST /api/chats/purge_trashed` - Manually purge old trashed chats
- `POST /api/chat` - Send a message and get response
- `POST /api/upload` - Upload a file
- `POST /api/url` - Scrape a URL
- `WebSocket /api/chat/stream` - Stream chat responses

## File Structure

```
ChatDO/
├── server/           # FastAPI backend
│   ├── main.py       # Main API server
│   ├── uploads.py    # File upload handling
│   ├── scraper.py     # URL scraping
│   ├── ws.py          # WebSocket streaming
│   └── data/
│       ├── projects.json
│       └── chats.json
├── web/               # React frontend
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── Sidebar.tsx
│   │   │   ├── ChatMessages.tsx
│   │   │   └── ChatComposer.tsx
│   │   └── store/
│   │       └── chat.ts
│   └── ...
└── uploads/           # Uploaded files (created automatically)
```

## Chat Trash and Retention

ChatDO includes a trash system for managing deleted chats:

- **Soft Delete**: When you delete a chat, it moves to Trash (not permanently deleted)
- **30-Day Retention**: Chats in Trash are automatically purged after 30 days
- **Manual Purge**: You can permanently delete chats from Trash immediately using "Delete now"
- **Auto-Cleanup**: On server startup, chats older than the retention period are automatically purged
- **Thread History**: When a chat is permanently deleted, its conversation history is also removed from disk

### Configuration

Set the retention period (in days) using the environment variable:

```bash
export CHATDO_TRASH_RETENTION_DAYS=30  # Default is 30 days
```

The retention period applies to chats that have been in Trash longer than the specified number of days. Trashed chats and their thread history are permanently deleted during server startup and can also be manually purged via the API.

## AI Router Configuration

The AI Router requires API keys for the AI providers. Create a `.env` file in the `packages/ai-router/` directory:

```bash
cd packages/ai-router
cat > .env << EOF
OPENAI_API_KEY=your-openai-api-key-here
AI_ROUTER_PORT=8081
EOF
```

**Note**: The `.env` file is gitignored and will not be committed to the repository.

## Troubleshooting

- **CORS errors**: Make sure the backend is running and CORS is configured for `http://localhost:5173`
- **WebSocket connection failed**: The app will automatically fall back to REST API
- **File upload not working**: Check that the `uploads/` directory is writable
- **Projects not loading**: Verify `server/data/projects.json` exists and is valid JSON
- **Chats not loading**: Verify `server/data/chats.json` exists and is valid JSON
- **AI Router errors**: Check that API keys are set in `packages/ai-router/.env` and the AI Router server is running

## Next Steps

- Add audio/video support
- Integrate Sora for video generation
- Multi-agent conversations
- Nebula integration
- Enhanced file extraction (OCR, etc.)

