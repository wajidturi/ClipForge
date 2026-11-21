# Pipeline: Moment Selection (Phase 4)

A **run** = "make N Shorts from these analysed sources". The `run.select` job turns scored sentences into a short list of **picks** (Shorts with status `picked`), each with a range, hook, title, hashtags, keywords, credit, score and reason. Picks can be edited or dropped before rendering (Phase 5).

## Flow

```mermaid
flowchart LR
  R[POST /runs] --> J[run.select]
  J --> W[candidate windows<br/>per source] --> K[top K candidates]
  K -->|free| H[heuristic picker]
  K -->|smart / deep| A[AI picker<br/>Ollama, schema JSON]
  A -- AI down or invalid --> H
  H & A --> V[validate<br/>whole sentences · speech ≥ 12 s · ≤ 90 s<br/>no overlap · ≤ 2 per source]
  V -- fewer than N --> T[top up from candidates] --> V
  V --> S[(shorts + parts,<br/>candidates, run.result)]
```

| Module | Role |
|---|---|
| `pipeline/selection/windows.py` | Every sentence-aligned window 15–60 s; score = 0.65·peak heat + 0.35·mean, +6 payoff in back half, −8 peak at the very start (no premise), +3 per extra signal type, −10 mid-thought opener ("and…", "he…"), −20 under 12 s of speech. Greedy non-overlapping top K. Flat windows (no peak) score 0 |
| `pipeline/selection/heuristic.py` | "No AI" mode: best candidates, ≤ 2 per source, near-duplicate texts skipped (Jaccard > 0.5), hook/title/hashtags from keywords and creator |
| `pipeline/selection/ai_picker.py` | AI chooses candidate **ids** only; it may move start/end by ≤ 10 s; unknown ids ignored; a score of 0 falls back to the signal score |
| `pipeline/selection/validate.py` | Snap to whole sentences; reject too short/long, overlapping, over the per-source cap; clean hook (≤ 6 words, caps), title (≤ 70), hashtags (3–5 + #shorts), keywords (≤ 3) |
| `pipeline/selection/callbacks.py` | Claim ("I bet…", "watch me…") 1 min–3 h before a hot payoff sharing a noun → listed on the run page |
| `pipeline/selection/evaluate.py` | Eval harness: precision/recall of picks vs labelled moments (IoU ≥ 0.3) |
| `ai/ollama.py` | Ollama `/api/chat` with `format` = JSON schema, `think: false`, one repair round on invalid JSON, readable errors (not running, model missing) |
| `ai/prompts.py` | Fixed system prompt with the selection rules; candidates in the user message; transcript wrapped in `<transcript>` and declared as data |
| `services/runs.py` | Orchestration, used-range exclusion (picks not rejected/dropped), fallback/top-up, persistence |
| `services/preview.py` | 4-frame preview strip per pick from the proxy or original video |

**Modes:** `free` (no AI), `smart` (AI reads candidate head…tail), `deep` (AI reads 2× more candidates with full text). Full-transcript reading for multi-hour streams does not fit a small local model's context, so "deep" works on candidates too.

**Fail-safe:** if the AI is unreachable, times out or returns invalid JSON twice, the run uses the heuristic and says so in `result.warnings`. If the AI returns fewer usable picks than asked, the rest are filled by signal score (also stated).

## Settings

| Env var | Default | |
|---|---|---|
| `CF_AI_PROVIDER` | `ollama` | `ollama` or `none` |
| `CF_OLLAMA_URL` | `http://127.0.0.1:11434` | |
| `CF_OLLAMA_MODEL` | `qwen3.5:4b` | any pulled model; a run can override it |
| `CF_AI_TIMEOUT_S` | 300 | per AI request |
| `CF_CANDIDATES_K` | 30 | candidates shown to the AI (deep: 2×) |

## API

| Method | Path | |
|---|---|---|
| POST | `/api/v1/runs` | `{source_ids, n, pick_mode, topic?, ai_model?}` |
| GET | `/api/v1/runs`, `/api/v1/runs/{id}` | run + picks (with parts, preview flag) + candidates |
| PATCH | `/api/v1/shorts/{id}` | hook, title, hashtags, keywords, start_s/end_s (snapped) — only while `picked` |
| DELETE | `/api/v1/shorts/{id}` | drop (soft; its range becomes free again) |
| GET | `/api/v1/shorts/{id}/preview.jpg` | 4-frame strip |
| GET | `/api/v1/ai/status` | provider, model, reachable, installed models |

WebSocket: `run.updated`.

## Verified

- 183 backend + 21 frontend tests (selection units, Ollama client against a mock server, runs end to end).
- Real end to end on this PC: a 100 s spoken test stream (Windows TTS) → upload → Whisper on CUDA → HEAT peaks at the bridge jump (≈45 s) and the race win (≈89 s) → Smart run with **qwen3.5:4b on Ollama**: both moments picked (36–54 s, 81–99 s) with fitting hooks, 42 s, 956 tokens, no warnings. "Watch" opens the source at the pick's start.
- Not measured: pick quality on real long streams (no labelled set yet; the eval harness is ready for one). Claude provider is not implemented yet (needs an API key).
