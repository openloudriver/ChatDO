# How to Verify the Memory Index is Working Correctly

## 1. Check Database Numbers Match

```bash
# Check actual index database
sqlite3 memory_service/store/privacypay-repo/index.sqlite \
  "SELECT COUNT(*) as files, COALESCE(SUM(size_bytes), 0) as bytes FROM files;"

# Check tracking database
sqlite3 memory_service/store/tracking.sqlite \
  "SELECT files_indexed, bytes_indexed FROM source_status WHERE id='privacypay-repo';"
```

**These should match!** If they don't, the tracking DB is out of sync.

## 2. Test Search Functionality

```bash
curl -X POST http://127.0.0.1:5858/search \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "test",
    "query": "privacy payment",
    "source_ids": ["privacypay-repo"],
    "limit": 5
  }'
```

If you get results with file paths and scores, the index is working!

## 3. Verify File Counts

```bash
# Count files in actual source repo (excluding node_modules, .git, etc.)
find /Users/christopher.peck/privacypay -type f \
  ! -path "*/node_modules/*" \
  ! -path "*/.git/*" \
  ! -path "*/dist/*" \
  ! -path "*/build/*" \
  | wc -l

# Compare to indexed files
sqlite3 memory_service/store/privacypay-repo/index.sqlite \
  "SELECT COUNT(*) FROM files;"
```

## 4. What "Reindex" Does

When you click "Reindex" for a source:

1. **Deletes the entire index database** for that source (all files, chunks, embeddings)
2. **Rescans the source directory** from scratch
3. **Re-extracts text** from all files
4. **Re-chunks** all text
5. **Re-generates embeddings** for all chunks
6. **Creates a new index database**

**This is a full rebuild** - it will take time proportional to the number of files.

**Use reindex when:**
- You've added many new files
- You've made significant changes to existing files
- The index seems corrupted or incomplete
- You've changed the include/exclude patterns in config

**You DON'T need to reindex when:**
- The watcher automatically picks up file changes
- You've made small edits to a few files
- The index is working correctly

## 5. Understanding the Size Numbers

**Dashboard "Size" (bytes_indexed):**
- Sum of source file sizes that were indexed
- Example: If you indexed 100 files of 1 MB each = 100 MB
- This is what the dashboard shows

**Finder Database Size:**
- The SQLite database file size on disk
- Includes: embeddings (vectors), chunks, metadata, indexes
- Much larger than source file sizes
- Example: 100 MB of source files → ~300-500 MB database

**Why the difference?**
- Each chunk gets a 384-dimensional embedding vector (~1.5 KB)
- A 1 MB source file might create 50 chunks = 75 KB of embeddings
- Plus SQLite overhead, indexes, etc.

## 6. Verify Index Completeness

```bash
# Check if all expected files are indexed
python3 << 'EOF'
import sqlite3
from pathlib import Path

db = Path("memory_service/store/privacypay-repo/index.sqlite")
conn = sqlite3.connect(str(db))
cursor = conn.cursor()

# Get sample of indexed files
cursor.execute("SELECT path FROM files LIMIT 10")
print("Sample indexed files:")
for (path,) in cursor.fetchall():
    print(f"  {path}")

# Check for common file types
cursor.execute("""
    SELECT filetype, COUNT(*) 
    FROM files 
    GROUP BY filetype 
    ORDER BY COUNT(*) DESC 
    LIMIT 10
""")
print("\nFile types indexed:")
for filetype, count in cursor.fetchall():
    print(f"  {filetype}: {count} files")

conn.close()
EOF
```

