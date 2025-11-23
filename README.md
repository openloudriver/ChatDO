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

For video summarization (YouTube, Bitchute, Rumble, etc.), set the following in your `.env` file:

- `FFMPEG_PATH` – optional, defaults to `ffmpeg`. On macOS with Homebrew, set to `/opt/homebrew/bin/ffmpeg`.
- `WHISPER_MODEL_NAME` – optional, defaults to `small`. Whisper model for local transcription.
- `WHISPER_COMPUTE_TYPE` – optional, defaults to `int8`. Compute type for Whisper (int8 works well on M1 Macs; alternatives: `int8_float16`, `float32`).

### Privacy Mode (Tier 3)

Privacy mode enables fully local summarization without any OpenAI API calls. When enabled:

- **Web pages**: Uses Trafilatura (local HTML extraction) + Llama-3.2 3B (local LLM)
- **Videos**: Uses Whisper-small (local transcription) + Llama-3.2 3B (local LLM)

To use privacy mode:

1. Download a Llama-3.2 3B instruct GGUF model (e.g., `llama-3.2-3b-instruct.Q4_0.gguf`) and place it in the `models/` directory.

2. Configure the following environment variables (optional, defaults shown):

   - `LOCAL_SUMMARY_MODEL_PATH` – defaults to `models/llama-3.2-3b-instruct.Q4_0.gguf`. Path to the GGUF model file.
   - `LOCAL_SUMMARY_CTX` – defaults to `8192`. Context window size for the local LLM.
   - `LOCAL_SUMMARY_THREADS` – defaults to `0` (auto). Number of CPU threads for inference.
   - `LOCAL_SUMMARY_N_GPU_LAYERS` – defaults to `0`. Number of layers to offload to GPU (if available).

3. In the "Summarize URL" dialog, toggle "Use Privacy mode (local only)" ON.

**Note**: Privacy mode requires the GGUF model file to be present at `LOCAL_SUMMARY_MODEL_PATH`. If the model is not found, the request will fail with an error.
