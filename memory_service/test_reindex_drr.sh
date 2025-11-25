#!/bin/bash
# Test script for reindexing and searching DRR source

echo "Reindexing DRR source..."
curl -X POST http://127.0.0.1:5858/reindex \
  -H "Content-Type: application/json" \
  -d '{"source_id": "drr-repo"}'

echo ""
echo ""
echo "Searching DRR source..."
curl -X POST http://127.0.0.1:5858/search \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the DRR?", "source_ids": ["drr-repo"], "limit": 5, "project_id": "drr"}'

echo ""

