# Memory Service Duplicate Instance Prevention

## Problem
Multiple Memory Service instances can run simultaneously, causing:
- Port conflicts (both trying to bind to port 5858)
- Database locks and corruption
- Timeout errors (Index-F in model labels)
- Resource contention

## Solution

We've implemented multiple layers of protection:

### 1. **Startup Check Module** (`memory_service/startup_check.py`)
- Checks if port 5858 is already in use
- Verifies if an existing process is actually Memory Service (via health check)
- Uses PID file tracking (`~/.chatdo/memory_service.pid`)
- Uses file-based locking (`~/.chatdo/memory_service.lock`)
- Automatically cleans up stale PID/lock files

### 2. **API-Level Protection** (`memory_service/api.py`)
- Startup checks run in the `lifespan` function before initialization
- If duplicate detected, service exits with clear error message
- PID file and lock are cleaned up on shutdown

### 3. **Safe Startup Script** (`scripts/start_memory_service.sh`)
- Checks for existing instances before starting
- Kills stale processes automatically
- Verifies successful startup via health check
- Provides clear status messages

## Usage

### Recommended: Use the Safe Startup Script
```bash
./scripts/start_memory_service.sh
```

This script will:
1. Check if port 5858 is in use
2. Verify if it's Memory Service (via health check)
3. Kill any stale processes
4. Start a new instance
5. Verify it started successfully

### Manual Start (Still Protected)
If you start manually with uvicorn, the API-level checks will still prevent duplicates:
```bash
python -m uvicorn memory_service.api:app --host 127.0.0.1 --port 5858
```

If another instance is running, you'll see:
```
[STARTUP] Memory Service is already running on 127.0.0.1:5858
[STARTUP] Exiting to prevent duplicate instance
RuntimeError: Cannot start: Memory Service is already running on 127.0.0.1:5858
```

### Launchd Service
If using launchd (via `install_memory_service_launchd.sh`), launchd itself prevents duplicates, but the startup checks provide additional safety.

## How It Works

### Port Check
1. Attempts to bind to port 5858
2. If port is in use, tries to connect to `/health` endpoint
3. If health check succeeds → Memory Service is running
4. If health check fails → port is used by something else

### PID File Check
1. Checks for `~/.chatdo/memory_service.pid`
2. If exists, reads PID and checks if process is alive
3. If process is alive, verifies it's Memory Service (via psutil if available)
4. If process is dead, removes stale PID file

### Lock File
1. Creates lock file exclusively
2. If lock file exists, checks if process is alive
3. If process is dead, removes stale lock and retries
4. Lock is released on shutdown

## Error Handling

- **Graceful degradation**: If `startup_check` module fails to import, startup continues (for development)
- **Stale file cleanup**: Automatically removes dead PID/lock files
- **Clear error messages**: Tells you exactly what's wrong and why

## Files Created

- `~/.chatdo/memory_service.pid` - Current process ID
- `~/.chatdo/memory_service.lock` - Lock file to prevent race conditions
- Both are automatically cleaned up on shutdown

## Testing

To test duplicate prevention:
1. Start Memory Service: `./scripts/start_memory_service.sh`
2. Try to start again: `./scripts/start_memory_service.sh`
3. Should see: "✅ Memory Service is already running on port 5858"

## Future Improvements

- Add `--force` flag to startup script to kill existing instance
- Add health check endpoint that includes PID for verification
- Add monitoring/alerting for stuck instances

