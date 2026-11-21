# ADR 0005 — AI providers: local Ollama first, schema-constrained JSON, always a fallback

**Status:** accepted (Phase 4) · **Date:** 2026-11-21

## Context
Moment selection benefits from a language model (premise/payoff judgement, hooks, titles), but the app must work offline and for free, and model output must never break the pipeline.

## Decision
- One `Provider` interface (`complete_json(system, user, schema)`); the first implementation is **Ollama** (local, free, private). Default model `qwen3.5:4b` (installed on the development PC); configurable per install and per run.
- Answers are constrained by the JSON schema of a Pydantic model (Ollama `format`), validated again on our side, with one repair round. The model only chooses **candidate ids** and may nudge times ≤ 10 s; ranges, rules and text limits are enforced by our validator.
- Transcript/chat text is wrapped and declared as data (prompt-injection hygiene).
- Every AI path has a deterministic fallback (the heuristic picker), and the run reports when it was used.
- A Claude provider (official `anthropic` SDK, structured outputs, prompt caching) is planned behind the same interface once an API key is available.

## Consequences
No cost and no data leaves the PC by default. Small local models judge less well than large hosted ones; the eval harness (`pipeline/selection/evaluate.py`) is how provider/model changes will be compared once a labelled set exists.
