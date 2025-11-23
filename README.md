# ChatDO — Director of Operations

Local dev-time AI that helps maintain repos
(PrivacyPay, DRR, etc.) using deep agents, planning, and filesystem tools.

**Version 1.0** - Now with persistent memory and thread-based conversations!

- Lives in `/Users/christopher.peck/ChatDO`
- Never ships to users
- Works against local checkouts like `/Users/christopher.peck/privacypay`
- Persistent memory per thread for long-running conversations

## Usage

### One-off tasks

```bash
cd ~/ChatDO
source .venv/bin/activate  # if using venv

# Example: review Credit Vault contracts in PrivacyPay
python -m chatdo --target privacypay \
  "Review packages/core/grow/creditvault/README.md and related policy/security files.
   List any inconsistencies and propose exact patches."
```

### Persistent threads (v1.0)

Use the `--thread` flag to maintain context across multiple conversations:

```bash
# Start a new thread for a project
python -m chatdo --target privacypay --thread credit-vault \
  "I want to finalize the Credit Vault product. Ask me clarifying questions first, then propose a README structure."

# Continue the same thread later
python -m chatdo --target privacypay --thread credit-vault \
  "Here are the answers to your questions: ... Now update the README accordingly."

# Next day, same thread - ChatDO remembers everything
python -m chatdo --target privacypay --thread credit-vault \
  "Continue where we left off. Now generate a checklist for Cursor to implement."
```

Thread history is stored in `memory/<target>/threads/<thread-id>/history.json` and persists across sessions.

## Features

**v1.0 Capabilities:**
- **Persistent Memory**: Long conversations tied to specific threads and targets
- **Planning & Execution**: ChatDO breaks down complex tasks and executes step-by-step
- **Repo-Aware**: Uses tools to list, read, and write files in your target repos
- **Architecture & Strategy**: Helps design systems, modules, and security models
- **Context Continuity**: Remembers decisions, conventions, and invariants across sessions

## How ChatDO Works

1. You write a *high-level* task for ChatDO, e.g.:

   ```bash
   python -m chatdo --target privacypay --thread security-architecture \
     "Review packages/core/security and propose a roadmap for tightening invariants."
   ```

2. ChatDO uses:
   - `list_files` to discover files
   - `read_file` to read them
   - `write_file` to make changes (or propose patches)
   - Memory to recall prior conversations in the thread

3. It responds with:
   - A short analysis
   - Proposed diffs / new sections you can copy into Cursor
   - Planning steps for complex tasks

You still stay in control:
- Review all proposed changes
- Let Cursor's agent review patches
- Run tests / linters
- Commit when you are comfortable

## Environment Variables

### Video Summarization (Tier 2)

For video summarization of non-YouTube hosts (Rumble, Bitchute, Archive.org, etc.), the following environment variables control the Whisper transcription pipeline:

- `FFMPEG_PATH` – optional, defaults to `ffmpeg`. On macOS with Homebrew, set to `/opt/homebrew/bin/ffmpeg`.
- `WHISPER_MODEL_NAME` – optional, defaults to `small`. Whisper model size for local transcription.
- `WHISPER_COMPUTE_TYPE` – optional, auto-detected based on hardware. On M1 Macs, defaults to `float16` for optimal performance. On other platforms, defaults to `int8`. Other options: `int8_float16`, `float32`.
- `WHISPER_DEVICE` – optional, auto-detected. On Apple Silicon (M1/M2/M3), defaults to `auto` (uses Metal/GPU acceleration). On other platforms, defaults to `cpu`. Set explicitly to `cpu` to force CPU-only mode.
- `WHISPER_THREADS` – optional, defaults to `0` (auto). Number of CPU threads for transcription. On M1 Macs, auto-detection uses 4-6 threads to keep UI responsive.

**M1 Mac Optimization**: The Whisper service is optimized for Apple Silicon with:
- FP16 compute type for reduced memory usage and better throughput
- Automatic Metal/GPU acceleration via faster-whisper's CTranslate2 backend
- Automatic fallback to CPU/FP32 on non-Apple hardware

### URL Summarization Pipeline

The system uses a deterministic 2-tier routing:

1. **Tier 1 (YouTube)**: `youtube-transcript-api` → GPT-5
   - Fast, text-based transcript extraction
   - No audio processing required

2. **Tier 2 (Other video hosts)**: `yt-dlp` → `Whisper-small-FP16` → GPT-5
   - Downloads audio via yt-dlp
   - Transcribes with local Whisper-small (FP16, M1-optimized)
   - Summarizes with GPT-5

3. **Web pages**: `Trafilatura` → GPT-5
   - HTML extraction and text summarization
