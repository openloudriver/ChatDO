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
```

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

## API Endpoints

- `GET /api/projects` - List available projects
- `POST /api/new_conversation` - Create a new conversation thread
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
│       └── projects.json
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

## Troubleshooting

- **CORS errors**: Make sure the backend is running and CORS is configured for `http://localhost:5173`
- **WebSocket connection failed**: The app will automatically fall back to REST API
- **File upload not working**: Check that the `uploads/` directory is writable
- **Projects not loading**: Verify `server/data/projects.json` exists and is valid JSON

## Next Steps

- Add audio/video support
- Integrate Sora for video generation
- Multi-agent conversations
- Nebula integration
- Enhanced file extraction (OCR, etc.)

