# ADR-0003: Multi-turn conversational chat (server-persisted) and the apps/web UI

## Status
Accepted

## Date
2026-07-11

## Context

`apps/web` is still unscaffolded — only empty `src/api/` and `src/components/` directories
exist, despite being documented (README.md, CLAUDE.md) as the target Vite + React + TypeScript
chat UI, and despite `docker-compose.yml` already declaring a `web` service that has nothing to
build (no `Dockerfile`, no `package.json`).

The existing `POST /query` (see ADR-0002) is single-shot: one question in, one grounded answer
out, no conversation memory. Building a real UI on top of it surfaced a design question bigger
than "scaffold a React app" — should the UI support multi-turn conversation, and if so:

1. Where does conversation state live, given there's no auth/user-account concept yet?
2. How does retrieval handle a follow-up question that lacks the keywords a fresh
   `hybrid_search` needs (e.g., after asking about eviction notice, "what about pets?")?
3. Does the grounded-answer contract (hard-abstain on empty retrieval, server-rebuilt
   citations — ADR-0002 §4) still hold once there's conversation history to draw on?

This ADR covers both the `apps/api` changes needed to support multi-turn conversation and the
`apps/web` scaffold itself, since the two were designed together (see `Consequences` for how
implementation may still split into separate phases/PRs).

## Decision

### 1. API shape: extend `POST /query`, not a new conversation resource

`QueryRequest` gains an optional `conversation_id`; `QueryResponse` gains a `conversation_id`
that's always present (newly created or continued). Omitting `conversation_id` starts a new
conversation; providing one continues it. One endpoint keeps prompt construction and the
grounded-answer contract entirely server-side — the frontend never assembles prompts or
history itself.

**Alternatives considered:**
- **Resource-oriented endpoints** (`POST /conversations`, `POST /conversations/{id}/messages`)
  — more RESTful and mirrors common chat-product APIs, but adds a second endpoint, more test
  surface, and an extra round-trip on first message (create conversation, then post into it)
  unless creation is folded into the first message post anyway — which mostly re-derives this
  decision with extra ceremony.
- **Client-side history stitching** (frontend builds the multi-turn prompt itself) — rejected:
  prompt construction is exactly what the `grounded-answer-contract` skill governs; moving it
  to the frontend leaks a backend concern across the API boundary, and still needs
  server-side persistence to survive a refresh, so it doesn't actually avoid backend work.

### 2. Conversation persistence: server-side Postgres, not client-only

New tables (`migrations/postgres/0002_conversations.sql`, mirroring the existing
`documents`/`chunks` UUID + FK + cascade pattern):

```sql
CREATE TABLE conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id      UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_index           INT NOT NULL,
    question             TEXT NOT NULL,
    standalone_question  TEXT,           -- reformulated query used for retrieval; null on turn 0
    answer               TEXT NOT NULL,
    citations            JSONB NOT NULL, -- serialized Citation[]
    abstained            BOOLEAN NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, turn_index)
);
```

**Alternative considered:**
- **Client-side only** (browser holds full history in state/`sessionStorage`, resends it every
  turn, no new tables) — simpler and needs no migration, but loses history on tab close and
  can't be the foundation for any future feature that needs the server to see a conversation
  (analytics, moderation, a future "resume on another device" without full auth). Rejected in
  favor of persistence since the schema cost is small and matches the existing per-document
  persistence pattern already in this repo.

### 3. Follow-up retrieval: Claude-based query reformulation before search

Before `hybrid_search` runs on turn *n > 0*, one plain (non-tool-forced) Claude call rewrites
the latest question into a standalone query using prior turns, so retrieval isn't blind to
context the raw follow-up doesn't restate. Turn 0 always skips this — zero added latency/cost
for single-turn usage, so existing golden-question eval behavior (`tests/evaluation/`) is
unaffected. The reformulation call **fails open**: if it errors, search falls back to the raw
question rather than failing the whole request — reformulation improves retrieval quality, it
isn't load-bearing for correctness the way the abstain/citation contract is.

**Alternatives considered:**
- **Search on the raw latest message only** — simplest, but follow-ups frequently retrieve
  irrelevant passages since `hybrid_search` never sees earlier context.
- **Concatenate the last 2-3 turns into the search query** — no extra LLM call, but a blunt
  heuristic that can dilute retrieval with stale keywords from earlier turns.

### 4. Grounded-answer contract holds per turn, history doesn't override it

`generate_answer` gains a `history` parameter. Prior turns replay as plain alternating
user/assistant messages (question/answer **text only** — not their original retrieved passage
blocks, so context doesn't grow unbounded turn over turn); the current turn's freshly-retrieved
passages are appended in the final user message exactly as in ADR-0002's single-shot design.
Each turn still hard-abstains if *that turn's* retrieval comes up empty — conversation history
provides context for phrasing/retrieval, not license to answer ungrounded.

### 5. Conversation scope: one active conversation per browser, no list/sidebar

The browser holds a single `conversation_id` in `localStorage`; opening the app resumes that
conversation or starts a new one. No "list past conversations" UI or API surface.

**Alternative considered:**
- **Multiple conversations with a sidebar** (list/switch/rename, closer to a full chat
  product) — rejected for v1: needs a `GET /conversations` endpoint and, to be meaningfully
  useful (vs. everyone with any conversation_id seeing everyone else's list), essentially
  needs auth first. Out of scope until auth exists.

### 6. Frontend stack: Vite + React + TypeScript + Tailwind, Vitest + RTL

Matches the README's already-documented target stack. Tailwind chosen over plain CSS (faster
layout iteration, most common default for new React projects) and over a component library
(shadcn/ui, MUI — adds dependency weight and a design-system opinion not needed for this
scope). Plain `useState`/`useReducer` for state — no Redux/Zustand; scope is one conversation,
no cross-page state. Vitest + React Testing Library for component/unit tests, matching the
rest of the repo's testing rigor; no Playwright/e2e for v1 (more setup/maintenance than this
scope currently justifies).

### 7. CORS

`apps/api` gets `CORSMiddleware` (currently absent) since the web dev server (`:5173`) calls
the API (`:8000`) cross-origin. Allowed origins come from a new `Settings.cors_allow_origins`
(default `["http://localhost:5173"]`), not hardcoded, consistent with the existing rule that
config belongs in `openlex_shared.config.Settings`.

## Consequences

- No auth exists yet, so `conversation_id` (an unguessable UUID) is effectively a
  bearer-token-style shared secret — anyone holding the id can read/continue that
  conversation. This is an accepted, explicit limitation of this ADR, not something it solves.
- `migrations/postgres/0002_conversations.sql` is the second real schema migration — the
  trigger point ADR-0001 anticipated ("no Alembic yet ... revisit when a second migration is
  needed"). This ADR still applies it as a plain SQL file, consistent with that earlier
  decision; moving to Alembic remains a separate future decision.
- Reformulation adds one Claude call per multi-turn message (not turn 0) — added latency and
  cost per follow-up question, deliberately bounded by the fail-open behavior in §3.
- History replay in `generate_answer` uses summarized question/answer text only, not full
  passage blocks from earlier turns — Claude doesn't re-see prior citations verbatim in later
  turns' context, only the persisted record does (each turn's citations are stored and
  returned independently, so nothing about display or the contract depends on replaying them).
- Single-conversation-per-browser scope (§5) means no multi-conversation API surface ships now;
  adding one later needs `GET /conversations` and realistically needs auth to be useful.
- This ADR's Decision section spans both `apps/api` and `apps/web`, but implementation is
  expected to land as two phases (backend fully testable via `pytest`/`curl` before any
  frontend code exists, then the `apps/web` scaffold against the live backend) — possibly as
  two separate PRs rather than one.
- Case-law retrieval still isn't covered (ADR-0002's open item) — multi-turn conversation over
  statute-only retrieval doesn't change that gap.
