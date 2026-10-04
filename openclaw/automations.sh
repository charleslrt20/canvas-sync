#!/usr/bin/env bash
# Creates the two Canvas reminder jobs. Run once, after the config patch is applied
# and the gateway is running. List them with: openclaw automations list
set -euo pipefail

OC="${OPENCLAW:-$HOME/.openclaw/bin/openclaw}"
TO="${TELEGRAM_CHAT_ID:-8629190292}" # your Telegram user ID = your DM chat ID
MODEL="${REMINDER_MODEL:-ollama/qwen3:8b}"
COMMON=(--tz "America/New_York" --session isolated --model "$MODEL" --announce --channel telegram --to "$TO")

"$OC" automations add "0 8 * * *" \
  "Morning brief. Use the canvas_lms tools: upcoming(days=2, only_unsubmitted=true), missing(), and announcements(days=1).
Reply with a short Telegram message:
☀️ Due in the next 48h: bullet list (title — course — due time), soonest first, or 'nothing 🎉'.
⚠️ Missing: bullet list, or omit this section if none.
📣 New announcements: one line each (course — title — one-sentence gist), or omit if none." \
  --name "Canvas morning brief" "${COMMON[@]}"

"$OC" automations add "0 20 * * *" \
  "Evening check. Use canvas_lms upcoming(days=1, only_unsubmitted=true). Keep only items due before 12:00 PM tomorrow.
If there are none, reply with exactly NO_REPLY and nothing else.
Otherwise reply: '🌙 Still to submit before tomorrow noon:' followed by a bullet list (title — course — due time)." \
  --name "Canvas evening check" "${COMMON[@]}"

"$OC" automations list
