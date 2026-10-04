# Canvas Assistant

A personal study assistant on Telegram (**@Canvas237_bot**) that knows your MIT Canvas: deadlines, missing work, announcements, grades and course files. It runs on [OpenClaw](https://docs.openclaw.ai) with free open models:

- **Chat:** GPT-OSS-120B on Groq's free tier, about 6 s per reply.
- **Reminders:** Qwen3 8B on Ollama, locally. They're sent at 8 AM and 8 PM.
- **Private mode:** `/model local` keeps a chat fully on your Mac, at 1.5–2.5 min per reply.

Design: [docs/superpowers/specs/2026-10-03-canvas-assistant-design.md](docs/superpowers/specs/2026-10-03-canvas-assistant-design.md)

```
Telegram ──► OpenClaw gateway (launchd, loopback-only)
                ├─ main agent: groq/openai/gpt-oss-120b  (/model local → ollama/qwen3:8b)
                ├─ reminders 8 AM / 8 PM: ollama/qwen3:8b
                └─ canvas_lms MCP server (canvas-mcp/, read-only, holds the token)
```

## Using it (Telegram)

| You send | What happens |
|---|---|
| "what's due this week?" | Looks up Canvas and lists deadlines |
| `/model local` | Private mode: this chat stays on your Mac (slow) |
| `/model cloud` | Back to Groq (fast) |
| `/new` | Starts a fresh conversation (also happens automatically after 30 idle min) |

## Layout

| Path | What |
|---|---|
| `canvas-mcp/` | Read-only Canvas MCP server (Python, `mcp` v2). Only sends GET requests to allowlisted API paths. |
| `openclaw/config.patch.json5` | Changes applied to `~/.openclaw/openclaw.json` (no secrets) |
| `openclaw/workspace/` | Assistant instructions, copied into `~/.openclaw/workspace/` |
| `openclaw/automations.sh` | Creates the two reminder jobs |
| `eval/questions.md` | 10-question check for picking the local model |

## Secrets (never committed)

| File | Contents | Read by |
|---|---|---|
| `Canvas_sync/.env` | `CANVAS_TOKEN`, `CANVAS_BASE_URL` | canvas-mcp only |
| `~/.openclaw/.env` | `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY` | OpenClaw gateway |

Both files should be `chmod 600`. Rotate the Canvas token at canvas.mit.edu → Account → Settings.

## Setup (from scratch)

```bash
# 1. Canvas server
cd canvas-mcp && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                       # unit tests
.venv/bin/python scripts/smoke.py      # live read-only check (needs ../.env)

# 2. Models and plugins
ollama pull qwen3:8b
openclaw plugins install @openclaw/groq-provider

# 3. OpenClaw config (back up first)
cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.pre-canvas
openclaw config patch --file openclaw/config.patch.json5 --dry-run
openclaw config patch --file openclaw/config.patch.json5
cp openclaw/workspace/*.md ~/.openclaw/workspace/
openclaw gateway restart && openclaw doctor && openclaw security audit

# 4. Reminders
bash openclaw/automations.sh
```

## Operations

- **Logs and status:** `openclaw doctor`, `openclaw automations list`, `openclaw mcp list`
- **Run a reminder now:** `openclaw automations run <jobId>`
- **Missed reminders:** if the Mac was asleep at 8 AM or 8 PM, the job runs when the gateway comes back. This is the default, `cron.skipMissedJobs: false`.
- **Restart the gateway:** `launchctl kickstart -k gui/$(id -u)/ai.openclaw.gateway`. `openclaw gateway restart` sometimes refuses with GATEWAY_RESTART_PREPARATION_REFUSED.
- **Rollback to the previous Claude setup:** `cp ~/.openclaw/openclaw.json.pre-canvas ~/.openclaw/openclaw.json && cp ~/.openclaw/workspace.pre-canvas/*.md ~/.openclaw/workspace/`, then restart the gateway.

## Moving to an always-on server (later)

Follow the official [Oracle Cloud Always Free guide](https://docs.openclaw.ai/install/oracle) (ARM, 4 CPU / 24 GB). Copy this repo and both `.env` files, then rerun the setup steps. Update the absolute paths in `mcp.servers.canvas_lms` in the patch. Ollama on the server's CPU will be slower, so consider `qwen3:8b` or making `cloud` the default there.

## Limitations

- **Groq free tier: not usable yet (decision pending).** It allows 8,000 tokens per minute, and no single request over 8,000. A question that uses a tool needs about 10–12k tokens (two calls), so in testing the chat worked for 1–2 questions and then hit rate limits. After that, summarizing the history also failed, and the conversation stayed broken until `/new` or the 30-minute reset. The options being considered are a free provider with higher limits, local only, or Groq with `/new` after every question.
- What you ask in chat, and the Canvas data it looks up, goes to Groq. Use `/model local` for anything you want to keep private.
- The bot can only read what's in Canvas. Many MIT classes post materials on their own course websites.
- Reminders only go out while the gateway is running.
- Scanned PDFs (images only) have no extractable text.
