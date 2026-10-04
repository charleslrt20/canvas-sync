# Model check

Used to choose the models. Outcome: local `qwen3:8b` was accurate but took 1.5–2.5 min per reply on a 16 GB M4. Groq's free tier failed after 1–2 questions. NVIDIA `nemotron-3-super-120b-a12b` answered all 7 back-to-back questions correctly in 1–11 s and is the chat model. Rerun this list after any model or config change.

Send each question on Telegram, first with `/model local` on `qwen3:8b`, then on `qwen3:14b`, and use `/new` between models. Score each answer:
- **Tool:** did it call the expected tool? (✅/❌)
- **Correct:** does it match Canvas? (✅/❌)
- **Seconds:** how long until it replied.

| # | Question | Expected tool(s) |
|---|---|---|
| 1 | What's due this week? | `upcoming(days=7)` |
| 2 | What do I still have to submit before Friday? | `upcoming(only_unsubmitted=true)` |
| 3 | Did I forget anything? | `missing` |
| 4 | What does the next 18.06 problem set ask for? | `list_courses` → `upcoming` → `assignment_details` |
| 5 | Any announcements in the last few days? | `announcements` |
| 6 | How am I doing in my classes? | `grades` |
| 7 | What were my scores in <course>? | `grades(course_id)` |
| 8 | What files are posted for <course>? | `list_files` |
| 9 | Summarize the most recent lecture slides in <course>. | `list_files` → `read_file` |
| 10 | Explain eigenvalues intuitively. | none (general knowledge) |

## Results

| # | 8B tool | 8B correct | 8B s | 14B tool | 14B correct | 14B s |
|---|---|---|---|---|---|---|
| 1 | | | | | | |
| 2 | | | | | | |
| 3 | | | | | | |
| 4 | | | | | | |
| 5 | | | | | | |
| 6 | | | | | | |
| 7 | | | | | | |
| 8 | | | | | | |
| 9 | | | | | | |
| 10 | | | | | | |

**Decision:** the default local model is whichever gets ≥ 9/10 on choosing the right tool and answers in under about 30 s. If neither does, revisit the design: the fallback is making the cloud model the default, which needs your OK first.
