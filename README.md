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

Run everything from the repo root. This setup is personal: `openclaw/config.patch.json5` contains this Mac's absolute path to `canvas-mcp/` (`mcp.servers.canvas_lms`) and one Telegram user ID (`allowFrom`), and `openclaw/automations.sh` has the same ID. If you clone the repo elsewhere, edit those first.

```bash
# 0. Secrets (never committed)
cp .env.example .env && chmod 600 .env          # then set CANVAS_TOKEN
touch ~/.openclaw/.env && chmod 600 ~/.openclaw/.env
#    add TELEGRAM_BOT_TOKEN=... and NVIDIA_API_KEY=nvapi-... to ~/.openclaw/.env

# 1. Canvas server
(cd canvas-mcp && python3 -m venv .venv && .venv/bin/pip install -r requirements.lock && .venv/bin/pip install --no-deps -e .)
canvas-mcp/.venv/bin/pytest canvas-mcp          # unit tests (pytest/respx are in the lockfile)
canvas-mcp/.venv/bin/python canvas-mcp/scripts/smoke.py   # live read-only check against Canvas

# 2. Local model for the 8 AM brief (the NVIDIA provider is bundled with OpenClaw)
ollama pull qwen3:8b

# 3. OpenClaw config (back up first)
cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.pre-canvas
mkdir -p ~/.openclaw/workspace.pre-canvas && cp ~/.openclaw/workspace/*.md ~/.openclaw/workspace.pre-canvas/
openclaw config patch --file openclaw/config.patch.json5 --dry-run
openclaw config patch --file openclaw/config.patch.json5
cp openclaw/workspace/*.md ~/.openclaw/workspace/
chmod 700 ~/.openclaw && chmod 600 ~/.openclaw/openclaw.json
launchctl kickstart -k gui/$(id -u)/ai.openclaw.gateway
openclaw doctor && openclaw security audit

# 4. 8 AM brief
bash openclaw/automations.sh
```

The `.env` path: `canvas_mcp/server.py` finds `Canvas_sync/.env` relative to the source tree, which works with the editable install above. Otherwise set `CANVAS_ENV_FILE=/path/to/.env`.

## Operations

- **Logs and status:** `openclaw doctor`, `openclaw automations list`, `openclaw mcp list`
- **Run a reminder now:** `openclaw automations run <jobId>`
- **Missed brief:** if the Mac was asleep at 8 AM, the job runs when the gateway comes back. This is the default, `cron.skipMissedJobs: false`.
- **Restart the gateway:** `launchctl kickstart -k gui/$(id -u)/ai.openclaw.gateway`. `openclaw gateway restart` sometimes refuses with GATEWAY_RESTART_PREPARATION_REFUSED.
- **Rollback to the previous Claude setup:** `cp ~/.openclaw/openclaw.json.pre-canvas ~/.openclaw/openclaw.json && cp ~/.openclaw/workspace.pre-canvas/*.md ~/.openclaw/workspace/`, then restart the gateway.

## Moving to an always-on server (later)

Follow the official [Oracle Cloud Always Free guide](https://docs.openclaw.ai/install/oracle) (ARM, 4 CPU / 24 GB). Copy this repo and both `.env` files, then rerun the setup steps. Update the absolute paths in `mcp.servers.canvas_lms` in the patch. Ollama on the server's CPU will be slower, so the 8 AM brief could also run on `cloud` there (`REMINDER_MODEL=nvidia/nvidia/nemotron-3-super-120b-a12b bash openclaw/automations.sh`).

## Security model

- **Telegram:** only one Telegram user ID can talk to the bot. Groups are off, and link previews are off so an injected URL can't be fetched silently.
- **Gateway:** bound to 127.0.0.1 with token auth.
- **Plugins:** only `telegram`, `ollama` and `nvidia` may load.
- **Tools:** the model sees exactly 8 tools, all read-only Canvas ones. Shell, files, browser, web, memory, sessions and messaging are all denied.
- **Canvas server** (`canvas-mcp/src/canvas_mcp/client.py`):
  - sends only GET requests, to an allowlist of API paths, over HTTPS to the Canvas host
  - never follows redirects on API calls
  - sends the token only to the Canvas host, never to the file CDN
  - streams downloads with a 50 MB cap and parses at most 300 PDF pages
- **Prompt injection:** `openclaw/workspace/AGENTS.md` tells the model that Canvas text is data, not instructions. This is a soft guard; the hard guarantees are the read-only tools and the absence of any way to send data out.
- **Secrets:** `.env` files are git-ignored and `chmod 600`. The repo itself contains no secrets.

## Limitations

- **Why NVIDIA rather than Groq:** Groq's free tier caps usage at 8k tokens/minute. A question that uses a tool needs 10–12k tokens, so chats broke after 1–2 questions. NVIDIA passed the same 7-question back-to-back test in 1–11 s per answer. It publishes no hard limits; community reports say about 40 requests/minute per model.
- **No local fallback in chat:** when the cloud model fails, the bot reports an error instead of switching to the local model. Switching stalled replies for minutes and used up the Mac's RAM.
- **Where your data goes:**
  - **NVIDIA** receives your chat messages and the Canvas data the bot looks up (grades, announcements, file text). Its free-API retention terms aren't published, so use `/model local` for anything private.
  - **Telegram** stores bot chats on its servers; bot chats aren't end-to-end encrypted.
  - **Canvas** logs each lookup as a page view, which instructors can see in course analytics.
- The bot can only read what's in Canvas. Many MIT classes post materials on their own course websites.
- The 8 AM brief only goes out while the gateway is running (a missed run catches up when the Mac wakes).
- Scanned PDFs (images only) have no extractable text.
