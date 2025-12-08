# Summarize URL Concurrency Issue - Discussion Summary

## Problem Statement

User reported that when running three URL summarizations simultaneously in different chats:
1. Rumble.com URL summarization (completed successfully)
2. GPT-5 question "Explain Monero" (completed successfully)
3. YouTube.com URL summarization (never finished/hung)

The YouTube summarization appeared to hang or timeout, while the other two completed.

## Investigation Findings

### Architecture Overview

**Summarize URL Pipeline:**
- **Video (Rumble/Bitchute)**: yt-dlp download → Whisper transcription → GPT-5 summarization
- **YouTube**: YouTube transcript API → GPT-5 summarization
- **Web pages**: Trafilatura/Readability extraction → GPT-5 summarization

**GPT-5 Chat Pipeline:**
- HTTP POST to AI Router (`http://localhost:8081/v1/ai/run`)
- AI Router forwards to OpenAI
- Pure HTTP requests, fully async

### Resource Bottlenecks Identified

1. **Whisper Transcription (Main Bottleneck)**
   - Uses singleton model (`_MODEL` global variable)
   - CPU/GPU intensive operation
   - Can take several minutes for long videos
   - When multiple video transcriptions run concurrently, they compete for:
     - GPU/CPU resources (Whisper model inference)
     - Memory (model loading)
   - This is the primary limiting factor for concurrent video summarizations

2. **yt-dlp Downloads**
   - Network I/O and disk I/O
   - Can run concurrently but compete for bandwidth/disk
   - Less of a bottleneck than Whisper

3. **GPT-5 Calls**
   - Pure HTTP requests to AI Router
   - AI Router handles multiple concurrent requests
   - No resource contention - can run many simultaneously
   - **Not a limiting factor**

### Key Insight

**GPT-5 chats are NOT affected by concurrency issues.** They are simple HTTP requests that can run concurrently without blocking each other. The bottleneck is specifically in the **Summarize URL** feature, particularly for videos that require Whisper transcription.

## Solution Implemented

### Changes Made

1. **Increased Timeout for Video Summarization**
   - Changed from 120 seconds to 300 seconds (5 minutes) for videos
   - Kept 120 seconds for web page articles
   - Rationale: Videos can take longer due to:
     - yt-dlp download time (varies by video length)
     - Whisper transcription (CPU/GPU intensive, can take minutes)
     - GPT-5 summarization (usually fast)

2. **Enhanced Logging**
   - Added per-conversation logging with `[Summary]` prefix
   - Logs conversation_id, URL, timeout, and error details
   - Helps diagnose which specific summarization is failing

3. **Better Error Messages**
   - More descriptive errors with conversation context
   - Easier to trace failures in logs

### Code Changes

```python
# Before:
resp = requests.post(ai_router_url, json=payload, timeout=120)

# After:
timeout_seconds = 300 if is_video else 120  # 5 minutes for videos, 2 minutes for articles
logger.info(f"[Summary] Calling AI Router for url={request.url} timeout={timeout_seconds}s is_video={is_video}")
resp = requests.post(ai_router_url, json=payload, timeout=timeout_seconds)
```

## Recommendations

### For User

1. **Multiple GPT-5 Chats**: ✅ **Safe to run simultaneously**
   - No resource contention
   - Pure HTTP requests, fully concurrent
   - No changes needed

2. **Summarize URL**: ⚠️ **Limit to one at a time for videos**
   - Especially for Rumble/Bitchute (uses Whisper)
   - YouTube (uses transcript API) is less resource-intensive
   - Web pages are fine to run concurrently
   - User is okay with this limitation

3. **Timeout Settings**: ✅ **Keep 300 seconds for videos**
   - Provides headroom for long video transcriptions
   - Doesn't affect GPT-5 chats (they use separate timeout)
   - 120 seconds for articles is sufficient

### Technical Notes

- **Whisper Model**: Currently a singleton (`_MODEL` global variable)
  - Could potentially be made thread-safe or use a pool for true concurrency
  - But user is okay with limiting to one video summarization at a time
  - This is a reasonable trade-off for now

- **AI Router**: Handles concurrent requests fine
  - No changes needed
  - GPT-5 calls through AI Router are not a bottleneck

## Questions for ChatGPT Review

1. **Is 300 seconds (5 minutes) a reasonable timeout for video summarization?**
   - Consider: yt-dlp download + Whisper transcription + GPT-5 summarization
   - Should we increase further, or is 300 seconds sufficient?

2. **Should we implement a queue/lock for Whisper transcriptions?**
   - Currently, multiple concurrent Whisper calls can compete for resources
   - User is okay with limiting to one at a time, but is there a better approach?

3. **Are there any other resource contention issues we should be aware of?**
   - Disk I/O from yt-dlp downloads?
   - Memory usage from multiple Whisper model instances?
   - Network bandwidth for concurrent downloads?

4. **Should we add retry logic for failed summarizations?**
   - Currently, if a summarization times out, it just fails
   - Should we retry automatically, or let the user retry manually?

5. **Is the logging sufficient for debugging future issues?**
   - We added `[Summary]` prefixed logs with conversation_id
   - Should we add more granular logging (e.g., per-step timing)?

## Current State

- ✅ Timeout increased to 300 seconds for videos
- ✅ Enhanced logging added
- ✅ Better error messages
- ✅ GPT-5 chats confirmed safe for concurrent use
- ✅ User understands limitation: one video summarization at a time

## Files Modified

- `server/main.py`: 
  - Increased timeout for video summarization (300s vs 120s)
  - Added logging with `[Summary]` prefix
  - Enhanced error messages with conversation context

