# Memory Service v1

Local-only indexing and search service for ChatDO projects.

## Overview

Memory Service provides automatic file indexing and semantic search capabilities for ChatDO projects. It uses local sentence-transformers embeddings (all-MiniLM-L6-v2) running on CPU, with no external API calls.

## Architecture

- **FastAPI HTTP Service**: Runs on `http://127.0.0.1:5858`
- **SQLite Database**: Stores sources, files, chunks, and embeddings in `memory_service/store/index.sqlite`
- **File Watchers**: Automatically index files when they're created, modified, or deleted
- **Embeddings**: Uses sentence-transformers with all-MiniLM-L6-v2 model (384-dimensional vectors)

## Installation

1. Install dependencies:
```bash
cd memory_service
pip install -r requirements.txt
```

2. Install Tesseract (for OCR):
```bash
# macOS
brew install tesseract

# Linux
sudo apt-get install tesseract-ocr
```

3. Configure sources in `config/memory_sources.yaml`

4. (Optional) Install as launchd service:
```bash
./scripts/install_memory_service_launchd.sh
```

## Usage

### Manual Start

```bash
cd memory_service
python -m uvicorn api:app --host 127.0.0.1 --port 5858 --reload
```

### API Endpoints

- `GET /health` - Health check
- `GET /sources` - List configured sources
- `POST /reindex` - Trigger full reindex of a source
  ```json
  {
    "source_id": "drr-repo"
  }
  ```
- `POST /search` - Search for relevant chunks
  ```json
  {
    "project_id": "drr",
    "query": "natural language question",
    "limit": 10
  }
  ```

### Testing

1. Start the service:
```bash
cd memory_service
python -m uvicorn api:app --host 127.0.0.1 --port 5858
```

2. Check health:
```bash
curl http://127.0.0.1:5858/health
```

3. Trigger initial index:
```bash
curl -X POST http://127.0.0.1:5858/reindex \
  -H "Content-Type: application/json" \
  -d '{"source_id": "drr-repo"}'
```

4. Test search:
```bash
curl -X POST http://127.0.0.1:5858/search \
  -H "Content-Type: application/json" \
  -d '{"project_id": "drr", "query": "What is this project about?", "limit": 5}'
```

## Integration with ChatDO

Memory Service is automatically integrated into ChatDO's chat flow. When a user sends a message in a project chat:

1. ChatDO backend calls Memory Service `/search` with the project_id and user message
2. Memory Service returns top-N relevant chunks from indexed files
3. Chunks are formatted as context and prepended to the system prompt
4. The AI model receives both memory context and the user's question

The integration is transparent - if Memory Service is unavailable, ChatDO continues without memory context.

## Supported File Types

- **Text/Code**: .txt, .md, .json, .ts, .tsx, .js, .py, .yml, .yaml, .toml, etc.
- **Documents**: .pdf, .docx, .rtf
- **Spreadsheets**: .xlsx, .xls, .csv
- **Presentations**: .pptx, .ppt
- **Images**: .png, .jpg, .jpeg (via OCR)

## Configuration

Edit `config/memory_sources.yaml` to add or modify indexed sources:

```yaml
sources:
  - id: drr-repo
    project_id: drr
    root_path: /Users/christopher.peck/DRR
    include_glob: "**/*"
    exclude_glob: "**/.git/**"
```

## Design Notes

- All indexing is local-only (no external APIs)
- Original files are never modified
- Index data lives separately in SQLite
- Automatic incremental indexing via file watchers
- Project-aware search (every chunk carries project_id)
- Designed for v2 extensibility (can swap embedding models, add TDA, etc.)

