# Canvas Assistant — Design

**Date:** 2026-10-03
**Status:** Draft, awaiting review

## Goal

A personal AI assistant you chat with on **Telegram**. It knows your MIT Canvas data (deadlines, assignments, announcements, grades, course files), sends proactive reminders, and answers general and coursework questions. It must cost nothing to run: open models only, either local (Ollama) or on a free cloud tier (Groq).

### Success criteria

- Messaging the bot on Telegram returns correct answers about your Canvas (for example "what's due this week?").
- `/model cloud` switches the chat to the free cloud model, and `/model local` switches it back.
- The 8:00 AM morning brief arrives on Telegram.
- Only you can talk to the bot, and the AI cannot run shell commands, touch the filesystem, or write to Canvas.

### Decisions made during brainstorming

| Decision | Choice | Why |
|---|---|---|
| Chat channel | Telegram | Official Bot API: no ban risk and no spare number needed. WhatsApp was rejected. |
| Agent framework | OpenClaw | Built-in Telegram, memory, scheduling, PDF handling and model switching |
| Model strategy | Local by default, manual switch to cloud | Canvas data stays local unless you choose otherwise |
| Agents | One agent (no tutor sub-agent) | Simpler, and handing work to other agents can be blocked entirely |
| Hosting | Your Mac first, Oracle Cloud Always Free later | Fast start. Moving later only requires a portable folder. |
| Canvas integration | Custom read-only MCP server | ClawHub skills are untrusted (the 2026 malicious-skill campaign) and need shell `exec` |

## Architecture

```
 You (Telegram) ──► OpenClaw gateway (Mac, launchd service, loopback-only)
                        │
                        ├─ single agent ── default model: ollama/qwen3 (local)
                        │     • Canvas Q&A, reminders, general Q&A
                        │     • /model cloud  → groq/<open model>  (free tier)
                        │     • /model local  → back to Ollama
                        │
                        └─ canvas-mcp (stdio MCP server, this repo)
                              • read-only Canvas REST client
                              • holds CANVAS_TOKEN; model never sees it
```

### Components

1. **OpenClaw gateway.** Installed with the official installer (`--no-onboard`) and configured by hand in `~/.openclaw/openclaw.json` (JSON5). It runs as a launchd background service (`openclaw gateway install`).
2. **Models**
   - `local`: `ollama/qwen3:8b`. If `qwen3:14b` is fast enough and calls tools more reliably, it becomes the default instead. Ollama `baseUrl` is `http://127.0.0.1:11434`, with no `/v1`, because the docs say `/v1` breaks tool calling.
   - `cloud`: a free Groq open model, picked when we set it up from `openclaw models list --provider groq`.
   - No automatic fallback between the two. Switching is manual so that Canvas data never goes to the cloud unexpectedly.
3. **canvas-mcp.** A Python MCP server (official `mcp` SDK, `httpx`, `pypdf`) in `canvas-mcp/`, registered with `openclaw mcp add` (stdio).
4. **Scheduled reminders.** Two OpenClaw automations. Both run on the local model, use time zone `America/New_York`, and announce to your Telegram chat.

## canvas-mcp

Base URL: `https://canvas.mit.edu/api/v1`. The token comes from `Canvas_sync/.env` (`CANVAS_TOKEN`).

| Tool | Purpose | Endpoint(s) |
|---|---|---|
| `list_courses` | Active courses | `GET /courses?enrollment_state=active` |
| `upcoming(days=7, course_id?)` | Upcoming items, with whether each is submitted | `GET /planner/items` |
| `missing()` | Missing submissions | `GET /users/self/missing_submissions` |
| `assignment_details(course_id, assignment_id)` | Description (HTML converted to text), points, rubric, submission status | `GET /courses/:id/assignments/:id?include[]=submission` |
| `announcements(days=14, course_id?)` | Recent announcements | `GET /announcements?context_codes[]=…` |
| `grades(course_id?)` | Current scores, plus per-assignment scores when a course is given | `GET /courses?include[]=total_scores`, `GET /courses/:id/students/submissions?student_ids[]=self` |
| `list_files(course_id, search?)` | Course files | `GET /courses/:id/files` |
| `read_file(file_id, page=1)` | Extracted text from a PDF or text file, split into chunks to stay within the model's context | `GET /files/:id` + download |

### Rules

- **Read-only by construction.** The HTTP client only sends `GET` requests to URLs that match an allowlist of path patterns. Anything else raises an error before any network call. File downloads must stay on the Canvas host or the Canvas file CDN redirect host it returns.
- **Pagination.** Follow `Link: rel="next"` headers, with a hard cap on pages.
- **Caching.** Keep results in memory for 10 minutes, keyed by request.
- **Errors.** Return short, model-readable errors ("Canvas token invalid or expired", "rate limited, retry later"). Never echo the token or raw headers.
- **Times.** Convert all timestamps to `America/New_York` before returning them.
- **Known limitation.** Course materials hosted outside Canvas (common at MIT) cannot be read.

## Reminders

| Job | Schedule | Content |
|---|---|---|
| Morning brief | Every day at 08:00 | Unsubmitted items due in the next 48 hours, missing work, announcements from the last 24 hours |
| Evening check | Every day at 20:00 | Unsubmitted items due before tomorrow at 12:00. **No message if there's nothing.** |

Not yet verified: whether OpenClaw catches up on jobs it missed while the Mac was asleep. Testing will cover this. If it doesn't catch up, we accept that limitation until the move to Oracle Cloud.

## Security

- **Telegram access:** `channels.telegram.dmPolicy: "allowlist"`, with `allowFrom` set to your numeric Telegram user ID, and groups disabled.
- **Gateway:** `gateway.bind: "loopback"` and `gateway.auth.mode: "token"`.
- **Tools:**
  - `tools.profile: "messaging"`
  - `tools.deny` blocks the runtime/exec, filesystem, browser and automation groups, plus `sessions_spawn`
  - `tools.exec.security: "deny"`
  - `tools.elevated.enabled: false`
- **Skills:** none installed from ClawHub.
- **Secrets:**
  - `Canvas_sync/.env` holds `CANVAS_TOKEN`, is git-ignored, and is read only by canvas-mcp.
  - The Groq key and Telegram bot token go in `~/.openclaw/.env`.
  - You type all secrets in yourself. They are never pasted into chat.
- **Upkeep:** run `openclaw security audit` after configuration changes, and keep OpenClaw updated because of the 2026 CVEs.

## Repo layout

```
Canvas_sync/
  canvas-mcp/
    pyproject.toml
    src/canvas_mcp/{server.py, client.py, tools.py, pdf.py}
    tests/            # pytest, mocked Canvas responses
  openclaw/
    openclaw.json5.template   # hardened config with placeholders
    automations.md            # exact commands for the reminder jobs
  docs/superpowers/specs/
  .env.example
  .gitignore                  # .env, caches
  README.md                   # setup + migration-to-Oracle notes
```

## Setup steps

| # | Step | Owner |
|---|---|---|
| 1 | Create the bot with @BotFather and get your numeric user ID from @userinfobot | You |
| 2 | Create the Canvas token and Groq key, and fill in the `.env` files | You |
| 3 | Install OpenClaw | Claude |
| 4 | `ollama pull qwen3:8b qwen3:14b` | Claude |
| 5 | Build and test canvas-mcp, then register it with OpenClaw | Claude |
| 6 | Write the hardened config | Claude |
| 7 | Create the automations and install the launchd service | Claude |

## Testing

1. **Unit tests (pytest).** Run every tool against mocked Canvas responses. Also test that non-GET methods and paths outside the allowlist are refused, that pagination works, and that the token never appears in outputs or errors.
2. **Live smoke test.** Run each tool once against your real Canvas account (read-only).
3. **Model check.** Put the same set of 10 questions to `qwen3:8b` and `qwen3:14b`. Score whether each picks the right tool, gives a correct answer, and how fast it is. Pick the default from the results.
4. **Security checks**
   - `openclaw security audit` reports no issues.
   - A message from a second Telegram account is ignored.
   - Asking the bot to run a shell command or read `~/.ssh` fails.
5. **Reminders.** Trigger both jobs by hand, then sleep the Mac through a scheduled time and record what happens.

## Risks

- **A small local model calls tools unreliably.** Mitigation: try the 14B model and tighten the tool descriptions. As a last resort, make the cloud model the default, but only after asking you, because that sends Canvas data to Groq.
- **Free-tier limits on Groq.** The cloud model is only used when you switch to it, so usage is low.
- **Reminders depend on the Mac being on** until the move to Oracle Cloud.

## Out of scope

WhatsApp, multiple agents, automatic model routing, writing anything to Canvas, indexing non-Canvas course websites, and the Oracle migration itself (only documented for later).

## Revisions after implementation (2026-10-04)

| Original design | Final | Reason |
|---|---|---|
| Local Qwen3 by default, `/model cloud` for Groq | **NVIDIA free API (Nemotron 3 Super 120B)** by default, gpt-oss-20b as fallback, `/model local` for private mode | Local 8B took 1.5–2.5 min per reply on a 16 GB M4. Groq's free tier (8k tokens/min) broke after 1–2 tool-using questions. NVIDIA passed the 7-question back-to-back test at 1–11 s per answer. |
| 8 AM brief + 8 PM check | **8 AM brief only** | Your choice |
| OpenClaw defaults | Tool Search off, no bundled skills, no heartbeat, `message`/`ask_user`/session tools denied, plugin allowlist | The 8B model couldn't drive Tool Search's indirect lookup tools; prompt size and latency; security audit |
| — | Chat resets after 30 idle min; Canvas tool output capped (10 announcements, 30 files, 4k-char file parts) | Keeps prompts small |
