# ADR 0004 — Tooling and quality gates

**Status:** accepted (Phase 1) · **Date:** 2026-11-21

## Decision
| Area | Backend | Frontend |
|---|---|---|
| Package manager | uv (lockfile `uv.lock`) | npm (lockfile `package-lock.json`) — already installed with Node, so no pnpm |
| Format | ruff format | prettier |
| Lint | ruff (incl. security `S`, bugbear `B`) | oxlint (ships with the Vite template; much faster than ESLint) |
| Types | mypy `--strict` | `tsc -b` (TypeScript 7) |
| Tests | pytest (+ PostgreSQL marker) | vitest + Testing Library (jsdom) |

- **API contract:** the backend's OpenAPI schema generates `frontend/src/lib/api/schema.d.ts` (`npm run gen:api`).
  `openapi-typescript` does not support TypeScript 7 as a peer yet, so it runs through `npx` instead of being a
  project dependency. CI regenerates the types and fails if they differ from the committed file.
- **pre-commit** runs ruff, prettier, oxlint and basic hygiene hooks on every commit.
- **CI** (GitHub Actions, `.github/workflows/ci.yml`): backend on Ubuntu + Windows, migrations on a real PostgreSQL 16 service, frontend checks + build, API contract check.

## Consequences
Every PR proves: formatting, lint, strict types, tests on both OSes, migrations on both databases, and that frontend types match the API.
