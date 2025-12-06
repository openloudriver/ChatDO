# Memory Service v1.1

Local-only indexing and search service for ChatDO projects.

## Progress & Health Dashboard (v1.1)

Memory Service v1.1 adds a comprehensive dashboard for monitoring indexing progress and source health.

### New Database Tables

**SourceStatus Table** (in `store/tracking.sqlite`):
- Tracks status, statistics, and last index times for each source
- Fields: `id`, `display_name`, `root_path`, `status`, `files_indexed`, `bytes_indexed`, `last_index_started_at`, `last_index_completed_at`, `last_error`, `project_id`

**IndexJob Table** (in `store/tracking.sqlite`):
- Tracks individual indexing jobs with progress
- Fields: `id`, `source_id`, `status`, `started_at`, `completed_at`, `files_total`, `files_processed`, `bytes_processed`, `error`

### New API Endpoints

- `GET /sources` - Returns all sources with status and latest job information
- `GET /sources/{source_id}/status` - Returns detailed status for a specific source
- `GET /sources/{source_id}/jobs` - Returns recent indexing jobs for a source
- `POST /reindex` - Now returns `job_id` for tracking progress

### Example Responses

**GET /sources:**
```json
{
  "sources": [
    {
      "id": "drr-repo",
      "display_name": "drr-repo",
      "root_path": "/Users/christopher.peck/DRR",
      "status": "idle",
      "files_indexed": 1250,
      "bytes_indexed": 45678901,
      "last_index_started_at": "2025-11-25T12:00:00",
      "last_index_completed_at": "2025-11-25T12:05:30",
      "last_error": null,
      "project_id": "drr",
      "latest_job": {
        "id": 1,
        "status": "completed",
        "files_total": 1250,
        "files_processed": 1250,
        "bytes_processed": 45678901,
        "started_at": "2025-11-25T12:00:00",
        "completed_at": "2025-11-25T12:05:30",
        "error": null
      }
    }
  ]
}
```

### Dashboard Features

- Real-time progress tracking during indexing
- Status indicators (idle, indexing, error, disabled)
- File and byte statistics
- Last index timestamps
- Error reporting
- One-click reindexing

## Overview

Memory Service provides automatic file indexing and semantic search capabilities for ChatDO projects. It uses local sentence-transformers embeddings (all-MiniLM-L6-v2) running on CPU, with no external API calls.

## Architecture

- **FastAPI HTTP Service**: Runs on `http://127.0.0.1:5858`
- **Per-Source SQLite Databases**: Each source has its own database at `memory_service/store/<source_id>/index.sqlite`
- **Global Tracking Database**: Status and job tracking in `memory_service/store/tracking.sqlite`
- **File Watchers**: Automatically index files when they're created, modified, or deleted
- **Embeddings**: Uses sentence-transformers with BAAI/bge-large-en-v1.5 model (1024-dimensional vectors)
- **Hybrid Search**: Combines vector similarity (60%) with BM25 keyword matching (40%) for improved search quality

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
- `GET /sources` - List all sources with status and latest job (v1.1)
- `GET /sources/{source_id}/status` - Get detailed status for a source (v1.1)
- `GET /sources/{source_id}/jobs` - Get recent indexing jobs for a source (v1.1)
- `POST /reindex` - Trigger full reindex of a source
  ```json
  {
    "source_id": "drr-repo"
  }
  ```
  Returns:
  ```json
  {
    "status": "ok",
    "job_id": 1,
    "source_id": "drr-repo",
    "files_indexed": 1250
  }
  ```
- `POST /search` - Search for relevant chunks
  ```json
  {
    "project_id": "drr",
    "query": "natural language question",
    "limit": 10,
    "source_ids": ["drr-repo"]
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

Memory Service uses **Unstructured.io** for maximum extraction quality across all file types:

- **Text/Code**: .txt, .md, .json, .ts, .tsx, .js, .py, .yml, .yaml, .toml, .xml, .html, .css, etc.
- **Documents**: .pdf (with superior table extraction), .docx, .doc, .rtf, .odt
- **Spreadsheets**: .xlsx, .xls, .csv, .ods
- **Presentations**: .pptx, .ppt, .odp
- **Images**: .png, .jpg, .jpeg, .gif, .bmp, .tiff, .webp (via OCR)
- **Email**: .eml, .msg
- **E-books**: .epub, .mobi

Unstructured provides the highest quality extraction, especially for:
- PDFs with complex tables and layouts
- Multi-column documents
- Documents with embedded images
- Structured data in spreadsheets

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

