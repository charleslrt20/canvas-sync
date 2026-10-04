# Canvas Assistant

A personal study assistant on Telegram (**@Canvas237_bot**) that knows your MIT Canvas: deadlines, missing work, announcements, grades and course files. It runs on [OpenClaw](https://docs.openclaw.ai) with free open models:

- **Chat:** Nemotron 3 Super 120B on NVIDIA's free API (build.nvidia.com), 1–11 s per reply, with gpt-oss-20b on the same API as fallback.
- **Reminder:** Qwen3 8B on Ollama, locally. A brief is sent every day at 8 AM.
- **Private mode:** `/model local` keeps a chat fully on your Mac, at 1.5–2.5 min per reply.

Design: [docs/superpowers/specs/2026-10-03-canvas-assistant-design.md](docs/superpowers/specs/2026-10-03-canvas-assistant-design.md)

```
Telegram ──► OpenClaw gateway (launchd, loopback-only)
                ├─ main agent: nvidia/nvidia/nemotron-3-super-120b-a12b
                │    fallback nvidia/openai/gpt-oss-20b · /model local → ollama/qwen3:8b
                ├─ 8 AM brief: ollama/qwen3:8b
                └─ canvas_lms MCP server (canvas-mcp/, read-only, holds the token)
```

## Using it (Telegram)

| You send | What happens |
|---|---|
| "what's due this week?" | Looks up Canvas and lists deadlines |
| `/model local` | Private mode: this chat stays on your Mac (slow) |
| `/model cloud` | Back to NVIDIA (fast) |
| `/new` | Starts a fresh conversation (also happens automatically after 30 idle min) |

## Layout

| Path | What |
|---|---|
| `canvas-mcp/` | Read-only Canvas MCP server (Python, `mcp` v2). Only sends GET requests to allowlisted API paths. |
| `openclaw/config.patch.json5` | Changes applied to `~/.openclaw/openclaw.json` (no secrets) |
| `openclaw/workspace/` | Assistant instructions, copied into `~/.openclaw/workspace/` |
| `openclaw/automations.sh` | Creates the 8 AM brief job |
| `eval/questions.md` | 10-question check for picking the local model |

## Secrets (never committed)

| File | Contents | Read by |
|---|---|---|
| `Canvas_sync/.env` | `CANVAS_TOKEN`, `CANVAS_BASE_URL` | canvas-mcp only |
| `~/.openclaw/.env` | `TELEGRAM_BOT_TOKEN`, `NVIDIA_API_KEY` | OpenClaw gateway |

Both files should be `chmod 600`. Rotate the Canvas token at canvas.mit.edu → Account → Settings.

## Setup (from scratch)

```bash
# 1. Canvas server
cd canvas-mcp && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                       # unit tests
.venv/bin/python scripts/smoke.py      # live read-only check (needs ../.env)

# 2. Models and plugins
ollama pull qwen3:8b            # NVIDIA provider is bundled with OpenClaw

# 3. OpenClaw config (back up first)
cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.pre-canvas
openclaw config patch --file openclaw/config.patch.json5 --dry-run
openclaw config patch --file openclaw/config.patch.json5
cp openclaw/workspace/*.md ~/.openclaw/workspace/
openclaw gateway restart && openclaw doctor && openclaw security audit

# 4. 8 AM brief
bash openclaw/automations.sh
```

## Operations

- **Logs and status:** `openclaw doctor`, `openclaw automations list`, `openclaw mcp list`
- **Run a reminder now:** `openclaw automations run <jobId>`
- **Missed brief:** if the Mac was asleep at 8 AM, the job runs when the gateway comes back. This is the default, `cron.skipMissedJobs: false`.
- **Restart the gateway:** `launchctl kickstart -k gui/$(id -u)/ai.openclaw.gateway`. `openclaw gateway restart` sometimes refuses with GATEWAY_RESTART_PREPARATION_REFUSED.
- **Rollback to the previous Claude setup:** `cp ~/.openclaw/openclaw.json.pre-canvas ~/.openclaw/openclaw.json && cp ~/.openclaw/workspace.pre-canvas/*.md ~/.openclaw/workspace/`, then restart the gateway.

## Moving to an always-on server (later)

Follow the official [Oracle Cloud Always Free guide](https://docs.openclaw.ai/install/oracle) (ARM, 4 CPU / 24 GB). Copy this repo and both `.env` files, then rerun the setup steps. Update the absolute paths in `mcp.servers.canvas_lms` in the patch. Ollama on the server's CPU will be slower, so consider `qwen3:8b` or making `cloud` the default there.

## Limitations

- **Why NVIDIA rather than Groq:** Groq's free tier caps usage at 8k tokens/minute. A question that uses a tool needs 10–12k tokens, so chats broke after 1–2 questions. NVIDIA passed the same 7-question back-to-back test in 1–11 s per answer. It publishes no hard limits; community reports say about 40 requests/minute per model.
- **No local fallback in chat:** when the cloud model fails, the bot reports an error instead of switching to the local model. Switching stalled replies for minutes and used up the Mac's RAM.
- What you ask in chat, and the Canvas data it looks up, goes to NVIDIA. Use `/model local` for anything you want to keep private.
- The bot can only read what's in Canvas. Many MIT classes post materials on their own course websites.
- Reminders only go out while the gateway is running.
- Scanned PDFs (images only) have no extractable text.
