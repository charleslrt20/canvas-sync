#!/usr/bin/env bash
# Creates the daily 9 AM Canvas brief. Run once, after the config patch is applied
# and the gateway is running. Check it with: openclaw automations list
set -euo pipefail

OC="${OPENCLAW:-$HOME/.openclaw/bin/openclaw}"
TO="${TELEGRAM_CHAT_ID:?Set TELEGRAM_CHAT_ID to your Telegram user ID (also your DM chat ID)}"
# Cloud, not ollama/qwen3:8b: at 9 AM the Mac is usually asleep with only seconds-long
# dark wakes, and the local model took 30-70 min there (timeouts, lost network).
MODEL="${REMINDER_MODEL:-nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b}"
COMMON=(--tz "America/New_York" --session isolated --model "$MODEL" --announce --channel telegram --to "$TO")

"$OC" automations add "0 9 * * *" \
  "Morning brief. Use the canvas_lms tools: upcoming(days=2, only_unsubmitted=true), missing(), and announcements(days=1).
Reply with a short Telegram message:
☀️ Due in the next 48h: bullet list (title — course — due time), soonest first, or 'nothing 🎉'.
⚠️ Missing: bullet list, or omit this section if none.
📣 New announcements: one line each (course — title — one-sentence gist), or omit if none." \
  --name "Canvas morning brief" "${COMMON[@]}"

"$OC" automations list
