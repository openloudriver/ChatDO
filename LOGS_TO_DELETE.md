# Log Files - Safe to Delete

All log files in the ChatDO project are **ephemeral** and can be safely deleted. They are regenerated automatically when services restart.

## Current Log Files

| File | Size | Last Modified | Purpose |
|------|------|---------------|---------|
| `ai-router.log` | 2.3K | Nov 30 23:33 | AI Router service logs |
| `frontend.log` | 13K | Nov 30 19:30 | Frontend (React) application logs |
| `memory_service.log` | 3.7K | Dec 7 15:19 | Memory Service backend logs |
| `server.log` | 369K | Dec 6 09:42 | Main backend server logs |
| `web.log` | 19K | Dec 1 00:50 | Web server logs |

## Recommendation

**All of these logs can be safely deleted** for a fresh start. They will be regenerated when:
- `ai-router.log`: AI Router service starts
- `frontend.log`: Frontend dev server starts (`pnpm dev`)
- `memory_service.log`: Memory Service starts
- `server.log`: Backend server starts
- `web.log`: Web server starts

## Why Delete?

Since you've deleted all chats to reset, deleting old logs will:
1. Remove noise from previous debugging sessions
2. Give you clean logs for the fresh start
3. Make it easier to see new issues without old errors cluttering the logs
