# How to Verify Memory Index Quality

## Quick Quality Check

### 1. Check Chunk Stats via API

```bash
# For Downloads source
curl -s "http://127.0.0.1:5858/sources/downloads-dir/chunk-stats" | python3 -m json.tool
```

**What to look for:**
- `total_chunks` > 0 (should have chunks)
- `total_files` matches expected file count
- `avg_chunk_size` should be reasonable (100-2000 chars)
- `duplicate_rate` should be low (< 20%)

### 2. Verify Embeddings Were Generated

```bash
python3 << 'EOF'
import sqlite3
from pathlib import Path

db_path = Path("memory_service/store/downloads-dir/index.sqlite")
conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# Check embeddings
cursor.execute("SELECT COUNT(DISTINCT chunk_id) FROM embeddings")
emb_count = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM chunks")
chunk_count = cursor.fetchone()[0]

print(f"Chunks: {chunk_count}")
print(f"Chunks with embeddings: {emb_count}")
print(f"Coverage: {emb_count/chunk_count*100:.1f}%")

if emb_count == 0:
    print("⚠️  WARNING: No embeddings generated! Search won't work.")
elif emb_count < chunk_count * 0.9:
    print("⚠️  WARNING: Some chunks missing embeddings")
else:
    print("✓ Embeddings look good!")

conn.close()
EOF
```

### 3. Test Search Functionality

```bash
# Test search with a query that should match your files
curl -s -X POST "http://127.0.0.1:5858/search" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "scratch",
    "query": "Joint Cloud",
    "source_ids": ["downloads-dir"],
    "limit": 5
  }' | python3 -m json.tool
```

**Expected:** Should return results with `score`, `text`, `file_path` if indexing worked.

### 4. Compare Across Sources

```bash
# Get stats for all sources
curl -s "http://127.0.0.1:5858/sources" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print('=== Index Comparison ===')
for s in sorted(data['sources'], key=lambda x: x['files_indexed'], reverse=True):
    print(f\"{s['id']:20} {s['files_indexed']:>6} files  {s['bytes_indexed']/1024/1024:>8.2f} MB\")
"
```

## Detailed Quality Metrics

### Good Index Quality Indicators:
- ✅ **Files indexed** matches expected count (minus excluded files)
- ✅ **Chunks per file** is reasonable (10-100 for typical documents)
- ✅ **Average chunk size** is 100-2000 characters
- ✅ **Embedding coverage** is > 95%
- ✅ **Search returns relevant results** for known content
- ✅ **Duplicate rate** is < 20%

### Warning Signs:
- ⚠️ **0 embeddings** → Search won't work, reindex needed
- ⚠️ **Very low chunk count** → Files might not be extracting text properly
- ⚠️ **Very high duplicate rate** (> 50%) → Chunking might be creating duplicates
- ⚠️ **Search returns no results** → Embeddings missing or query doesn't match

## What the Dashboard Shows

The Memory Dashboard shows:
- **Files indexed**: Number of files successfully indexed
- **Size**: Total bytes of source files indexed
- **Status**: `idle` (done), `indexing` (in progress), `error` (failed)
- **Last Index**: When indexing completed

**Note:** The dashboard doesn't show embedding status. Use the API endpoints above to verify embeddings were generated.

## Common Issues

### Issue: Indexed files but search returns nothing
**Cause:** Embeddings weren't generated (bug or error during indexing)
**Fix:** Reindex the source

### Issue: Files indexed but chunk count is very low
**Cause:** Text extraction failed or returned empty text
**Fix:** Check logs for extraction errors, verify file types are supported

### Issue: Indexing seems too fast
**Cause:** Many files were skipped (unsupported types, empty text, etc.)
**Fix:** Check logs for `[MEMORY] Skipping file` messages

## Next Steps After Reindex

1. **Wait for indexing to complete** (status changes to `idle`)
2. **Check chunk stats** to verify files were indexed
3. **Verify embeddings** were generated (critical for search)
4. **Test search** with a known query
5. **Compare** with other sources to ensure quality is similar

