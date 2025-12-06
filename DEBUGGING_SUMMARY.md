# Memory Dashboard Auto-Update Debugging Summary

## Problem Statement
The Memory Dashboard was not automatically updating when files were added, modified, or deleted in the monitored directory (`/Users/christopher.peck/Coin`). Specifically:
- Files dropped into the directory (including "Test File.rtf") were not being indexed
- File counts and sizes in the dashboard were not updating
- The dashboard showed "Last Index: 26m ago" even after file changes

## System Architecture Overview
- **Memory Service**: FastAPI service running on port 5858 that manages file indexing
- **Watcher System**: Uses `watchdog` library for file system events + periodic directory scanning
- **Indexer**: Processes individual files (extracts text, chunks, embeds, stores in SQLite)
- **Dashboard**: React frontend that displays source status from tracking database
- **Tracking Database**: Stores `source_status` table with `files_indexed`, `bytes_indexed`, `last_indexed_at`
- **Per-Source Databases**: Each source has its own SQLite database with `files` table

## All Changes Made

### 1. Initial Fix: Added Source Stats Updates in `indexer.py`

**File**: `memory_service/indexer.py`

**Problem**: When `index_file()` successfully indexed a file, it wasn't updating the `source_status` table, so the dashboard metrics didn't change.

**Changes**:
- Added `db.update_source_stats()` call after successful file indexing (line ~538)
- Added `db.update_source_stats()` call after metadata-only updates (line ~490)
- Added `db.update_source_stats()` call in `delete_file()` function (line ~678)

**Code Added**:
```python
# After successful indexing:
conn = db.get_db_connection(source_id)
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM files")
row = cursor.fetchone()
actual_files = row[0] if row else 0
actual_bytes = row[1] if row and len(row) > 1 else 0
conn.close()

db.update_source_stats(
    source_id,
    files_indexed=actual_files,
    bytes_indexed=actual_bytes
)
```

### 2. Added Periodic Directory Monitor

**File**: `memory_service/watcher.py`

**Problem**: File system events from `watchdog` were unreliable on macOS, especially for drag-and-drop operations. Events could fire before files were fully written, or not fire at all.

**Solution**: Implemented a hybrid approach - keep event-based watcher but add a periodic directory scanner that runs every 2 seconds as a fallback.

**Changes**:
- Added `scan_threads` and `scan_stop_flags` dictionaries to `WatcherManager` class
- Added `scan_interval = 2` (scans every 2 seconds)
- Created `_start_periodic_scan()` method that starts a background thread
- Created `_scan_directory_for_changes()` method that:
  - Retrieves all indexed files from database with their `modified_at` and `size_bytes`
  - Scans the actual directory using `root_path.rglob('*')`
  - Compares the two sets to find new, modified, and deleted files
  - Calls `index_file()` for new/modified files
  - Calls `delete_file()` for deleted files

**Key Implementation Details**:
- Monitor runs in a daemon thread with `monitor_loop()` function
- Runs initial scan immediately on startup, then periodic scans every 2 seconds
- Uses `stop_event.wait(self.scan_interval)` for timing
- Thread is named `DirMonitor-{source_id}` for debugging

### 3. Fixed macOS File Creation Race Condition

**File**: `memory_service/watcher.py` - `IndexingHandler.on_created()`

**Problem**: On macOS, `on_created` events can fire before the file is fully written to disk, causing `path.exists()` to return False or incomplete reads.

**Changes**:
- Added `time.sleep(0.1)` delay after receiving creation event
- Added explicit `if not path.exists(): return` check
- Added more detailed logging to track event reception

### 4. Fixed Path Normalization for Deletion Detection

**File**: `memory_service/watcher.py` - `_scan_directory_for_changes()`

**Problem**: When detecting deleted files, paths stored in database might be relative or in different format than paths resolved during scan, causing mismatches.

**Changes**:
- Store both `original_path` (as stored in DB) and `normalized_path` (absolute resolved path) in `indexed_files` dictionary
- When checking for deletions, iterate through `indexed_files` and:
  - Check if `normalized_path` exists in `current_files` (which also uses normalized paths)
  - If not found, use `original_path` to check `path.exists()` on filesystem
  - Only call `delete_file()` if file truly doesn't exist

**Code Structure**:
```python
indexed_files[indexed_path_normalized] = {
    'original_path': indexed_path_str,  # Keep original for deletion
    'modified_at': modified_at,
    'size_bytes': row[2] if row[2] else 0
}
```

### 5. Fixed Modification Detection Logic

**File**: `memory_service/watcher.py` - `_scan_directory_for_changes()`

**Problem**: The original logic had a flaw where it would check `is_new = normalized_path not in indexed_files`, and only if that was False would it check for modifications. However, if the normalized path WAS in indexed_files, it would skip the modification check entirely.

**Changes**:
- Restructured logic to:
  1. First check if normalized path matches any indexed file
  2. If not, check if any indexed file's original path matches
  3. If found, set `matched_indexed_info` and `is_new = False`
  4. If not found, mark as new
  5. If already indexed, ALWAYS check for modifications using timedelta comparison

**New Logic Flow**:
```python
is_new = True
matched_indexed_info = None

if normalized_path in indexed_files:
    matched_indexed_info = indexed_files[normalized_path]
    is_new = False
else:
    # Check original paths
    for idx_norm, idx_info in indexed_files.items():
        idx_original_path = Path(idx_info['original_path'])
        if idx_original_path.resolve() == path.resolve():
            matched_indexed_info = idx_info
            is_new = False
            break

if is_new:
    new_files.append(path)
else:
    # Always check for modifications
    if matched_indexed_info:
        indexed_mtime = matched_indexed_info['modified_at']
        time_diff = abs((modified_at - indexed_mtime).total_seconds())
        if time_diff > 1.0 or size_bytes != matched_indexed_info['size_bytes']:
            modified_files.append(path)
```

### 6. Fixed Datetime Comparison

**File**: `memory_service/watcher.py` - `_scan_directory_for_changes()`

**Problem**: Using exact equality (`==`) for datetime comparison is too strict. SQLite stores datetimes as strings, and when parsed back, there can be microsecond precision differences or timezone issues.

**Changes**:
- Changed from `modified_at != indexed_mtime` to `time_diff > 1.0` where `time_diff = abs((modified_at - indexed_mtime).total_seconds())`
- This allows for 1-second tolerance to handle precision differences
- Also checks `size_bytes != matched_indexed_info['size_bytes']` as a separate condition

**Datetime Parsing**:
- Added robust datetime parsing in `_scan_directory_for_changes()`:
  - First tries `datetime.fromisoformat()`
  - Falls back to `dateutil.parser.parse()` if available
  - Falls back to `datetime.now()` if parsing fails

### 7. Added Extensive Debug Logging

**File**: `memory_service/watcher.py`

**Changes**: Added special logging for "Test File" throughout the scan process to trace:
- When file is found during `rglob()` scan
- When file passes/fails filter checks
- When file is detected as new vs. already indexed
- When file modification comparison occurs
- When file is added to `modified_files` list

**Logging Points**:
- When Test File is found in indexed files from database
- When Test File is found during directory scan
- When Test File is filtered out by `_should_ignore_path()`
- When Test File is filtered out by `should_index_file()`
- When Test File passes filters
- When Test File is detected as new
- When Test File modification comparison happens
- When Test File is detected as modified

### 8. Enhanced Error Handling

**File**: `memory_service/watcher.py`

**Changes**:
- Added try/except around entire `monitor_loop()` function
- Added try/except around each periodic scan iteration
- Added logging for scan count to track if scans are running
- Added thread naming for easier debugging
- Added logging when directory monitor thread starts with thread ID

## Current State

### What Works
- The directory monitor thread starts successfully
- New files ARE being detected (file count increased from 19 to 21 during testing)
- The periodic scan runs every 2 seconds
- Source stats are updated when files are indexed

### What Doesn't Work
- "Test File.rtf" is NOT being detected, even though:
  - The file exists at `/Users/christopher.peck/Coin/Test File.rtf`
  - The file has text content (414 bytes, RTF format)
  - RTF files are supported (`.rtf` is in `DOCX_EXTENSIONS`)
  - The file is not excluded by glob patterns
  - The file can be found by `rglob('*')` when tested manually
  - The file was modified at 09:39 (visible in Finder)

### Observations
1. **No Test File logs**: Despite extensive logging for "Test File", NO logs appear in the service logs when searching for "test file" (case-insensitive). This suggests:
   - The file is not being found during the scan, OR
   - The file is being filtered out before logging, OR
   - The scan is not running for this specific file

2. **Other files ARE detected**: Test files created during debugging (`test_manual_*.txt`, `test_scan_verification.txt`) WERE detected and indexed, increasing the count from 19 to 21.

3. **Service is running**: The service is healthy and responding to API calls.

4. **Monitor thread starts**: Logs show directory monitor setup, but we don't see scan completion logs consistently.

## Files Modified

1. `memory_service/indexer.py`
   - Added `update_source_stats()` calls after indexing and deletion
   - Lines: ~490, ~538, ~678

2. `memory_service/watcher.py`
   - Added periodic directory monitor system
   - Fixed modification detection logic
   - Fixed datetime comparison
   - Added extensive logging
   - Fixed path normalization
   - Lines: Throughout, major changes in `_scan_directory_for_changes()` method

## Configuration

- **Scan Interval**: 2 seconds
- **Source ID**: `coin-dir`
- **Root Path**: `/Users/christopher.peck/Coin`
- **Include Glob**: `**/*`
- **Exclude Glob**: `**/.git/**,**/node_modules/**,**/dist/**,**/build/**,**/.next/**,**/.turbo/**,**/.cache/**,**/.venv/**,**/venv/**,**/*.sqlite,**/*.sqlite-journal,**/*-wal`

## Testing Performed

1. ✅ Created test files - they were detected and indexed
2. ✅ Verified service restarts successfully
3. ✅ Verified directory monitor thread starts
4. ❌ "Test File.rtf" modifications not detected
5. ❌ No logs appear for "Test File" despite extensive logging

## Potential Root Causes (Unresolved)

1. **File Already Indexed**: The file might have been indexed during initial full index, and modification detection is failing silently due to:
   - Datetime comparison still too strict (even with 1-second tolerance)
   - Path matching issue (normalized vs. original path mismatch)
   - Database query not finding the file correctly

2. **Filtering Issue**: The file might be filtered out by:
   - `_should_ignore_path()` - but RTF files shouldn't be ignored
   - `should_index_file()` - but RTF is in supported extensions
   - Glob patterns - but tested and confirmed not excluded

3. **Scan Not Running**: The periodic scan might not be running for this specific file due to:
   - Exception being caught silently
   - File not being found by `rglob('*')` for some reason
   - Thread not actually running despite appearing to start

4. **Database Issue**: The file might be in the database but:
   - Path stored differently than expected
   - Datetime stored in unexpected format
   - Query not matching correctly

## Next Steps for Investigation

1. **Check if file is in database**: Query the database directly to see if "Test File.rtf" exists and what path/datetime is stored
2. **Add more logging**: Log EVERY file found during scan, not just Test File
3. **Check thread status**: Verify the monitor thread is actually running and not crashing
4. **Manual test**: Try manually calling `index_file()` on Test File.rtf to see if it works
5. **Check logs more carefully**: Look for any exceptions or errors that might be silently caught
6. **Verify file permissions**: Ensure the file is readable
7. **Check if file is a symlink**: Symlinks might not be resolved correctly

## Key Code Locations

- **Directory Monitor**: `memory_service/watcher.py`, lines 217-524
- **File Indexing**: `memory_service/indexer.py`, lines 423-570
- **Source Stats Update**: `memory_service/indexer.py`, lines 490-496, 530-545
- **File Deletion**: `memory_service/indexer.py`, lines 654-690
- **Database Operations**: `memory_service/store/db.py`

## Log Locations

- Service logs: `~/Library/Logs/chatdo-memory-service.log`
- Error logs: `~/Library/Logs/chatdo-memory-service.error.log`

## Service Management

- Service runs via launchd: `~/Library/LaunchAgents/com.chatdo.memoryservice.plist`
- Restart command: `launchctl unload ~/Library/LaunchAgents/com.chatdo.memoryservice.plist && launchctl load ~/Library/LaunchAgents/com.chatdo.memoryservice.plist`
- Health check: `curl http://127.0.0.1:5858/health`
- Sources endpoint: `curl http://127.0.0.1:5858/sources`

