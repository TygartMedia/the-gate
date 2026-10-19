# Build Spec — The Gate: a governed memory wrapper for MongoDB Agent Engine

**Date:** 2026-10-19 · **Status:** spec, approved by Will ("Write the build spec") · **Evidence base:** three GLM 5.3 Flash Max agent runs, 2026-10-19 (model capabilities · Mongo memory gaps · live interview shelf-sort), plus the Oct 13 Atlas Agent Engine walkthrough in `~/memory/2026-10-13.md`.

## 1. What this is

MongoDB Agent Engine supplies the memory substrate: four long-term memory types ("the shelves") — **semantic, episodic, taxonomic, procedural** — plus retrieval. It does **not** supply the discipline. Left alone, it writes ungated facts and can never delete them.

**The build is the wrapper — the gate — that sits between a conversation and that store.** The wrapper is the only writer. It decides what earns a shelf, refuses what doesn't, and assembles every prompt context so that only approved facts ever come back in.

This is the distillery, productized: a human's raw output goes in one end; only distilled, gated memory reaches the shelves.

## 2. Execution model

- **Sorter model: GLM 5.3 Flash Max** (Cursor picker name "GLM 5.3 Flash Max"; there is no separate non-Flash "5.3 Max" in the session picker). Chosen because the 2026-10-19 live interview test passed on it (see §8).
- If GLM 5.3 Flash Max is unavailable, **stop — do not substitute** a lower tier. LOW-tier output false-certifies; the gate is the product, and a weaker gate is worse than no gate.
- **If-then cue (binding on every builder of this spec):** if a step's end state can't be verified, then stop that step, log HOLD with the reason, and move to the next independent step — never improvise past a failed check or report an unverified step as done.

## 3. Architecture

```
speech ──► Cursor mic (speech→text) ──► finished utterance
                                              │
                                              ▼
                                     ┌─────────────────┐
                                     │  SORTER (GLM)   │  emits tool calls only:
                                     │                 │  shelf_write{shelf, content, op}
                                     └────────┬────────┘
                                              ▼
                                     ┌─────────────────┐
                                     │   GATE (rules)  │  allow / refuse / ask-one-question
                                     └────────┬────────┘
                                              ▼ approved only
                                     ┌─────────────────┐      ┌──────────────────┐
                                     │  SDK WRITER     │─────►│  MONGO SHELVES   │
                                     └─────────────────┘      │  semantic        │
                                                                │  episodic        │
   TRACE (per-turn thinking) ──► separate local store,          │  taxonomic       │
   NEVER inside Mongo; wiped at next conversation start         │  procedural      │
                                                                └────────┬─────────┘
                                              ┌───────────────────────────┘
                                              ▼ read path
                                     CONTEXT BUILDER — wrapper-assembled;
                                     approved shelf facts only; flagged facts
                                     excluded; explicit session filter applied
```

Components:

1. **Ingest boundary.** Input is *finished utterances only*. The model reads text (the microphone makes text first); nothing is sorted mid-sentence.
2. **Sorter.** GLM 5.3 Flash Max reads the utterance and calls a `shelf_write` **tool** — shelf choice is a tool call carrying a shelf name, never a paragraph the wrapper parses.
3. **Gate.** Deterministic rules (§5) allow, refuse, or convert a proposed write into exactly one clarifying question.
4. **SDK writer.** The only component that writes shelves. The Mongo memory **connector cannot write the four long-term types** (record-turn + search only) — all shelf writes go through the SDK.
5. **Trace store.** Chain-of-thought lives in a separate local store **beside** Mongo, never inside it (see §4.2).
6. **Context builder.** Assembles prompt context from approved shelf facts only. Because the wrapper assembles context, it can exclude flagged facts even though the store cannot delete them (§4.2).

## 4. Hard constraints (from the Mongo gaps pass — these are load-bearing)

### 4.1 Auto-distillation must be OFF
About three minutes after a conversation stops, Atlas can run a *different* model over the same turns and write facts straight onto the shelves — skipping the gate entirely. **Extraction is configured `enabled: []`.** The wrapper is the only writer. Acceptance includes proving no write appears after an idle wait (§8, test 5).

### 4.2 Nothing can be deleted — design around permanence
The current API has **no client delete and no expiry** on long-term memory. Consequences:
- Prevention is the only real control: the gate is strict because mistakes are forever.
- The **trace never enters the store** — `build_context` would pull it back into future prompts.
- Remediation for a bad fact is *supersede + flag*: a replacement write supersedes it, and the wrapper-side flag index excludes it from every context the builder assembles. The bytes remain in Mongo; they never reach a prompt again. This residual risk is accepted explicitly for v1.

### 4.3 Writes are utterance-shaped and atomic
One breath routinely hits two or three shelves. **All shelf writes from one utterance commit together** (one transaction from the caller's point of view) or none do. A changed rule **replaces** the old one — it never sits beside it.

### 4.4 Trace lifetime = one turn, wipe at conversation start
Z.ai's tool loop expects the thinking returned *with* the tool result inside the same turn — wiping mid-turn makes the hands worse. So: trace is kept for the current turn only and **wiped at the start of the next conversation**. That wipe is the default on the standard API path.

### 4.5 Session filter is explicit
Consolidated episodes are stored with **no session id** (confirmed in Mongo's docs; the Oct 13 amnesia note is real). SDK 0.11.7 no longer applies the live session as a filter on its own, so the bug now takes an explicit stale filter or an old SDK. **The context builder applies its session filter explicitly, in wrapper code, and pins the SDK version.** No implicit filtering is trusted.

### 4.6 Domain terms are project-shared
A term defined by one person becomes the shop's word for everyone in the project. V1 is therefore **single-project, single-operator**. Shared-vocabulary effects are a v2 problem, named here so nobody "discovers" them in production.

## 5. Gate rules (from the interview test — the refusals are the spec)

The sorter proposes; these rules dispose. Each was demonstrated live on 2026-10-19:

1. **No global law from one sentence.** A single utterance can create a scoped fact or a draft rule; it cannot mint a standing law for everyone. Over-broad proposals are narrowed or refused.
2. **No state change from a breath.** A spoken line cannot mutate external state (e.g., a calendar) directly. It can record the *fact* ("the Seattle day is cancelled" — episodic) and raise the action; the action itself goes through its own channel.
3. **No invented definitions.** If a term's filing target or meaning is unknown (the test case: "work order"), the gate does not guess — it asks **one** question. (House answer, for our deployment: a work order files at `~/workspace/work-orders/wo-NNN-<slug>.md`, materials via the Drive handoff folder.)
4. **No false runtime claims.** The sorter may not assert a system state that contradicts the live one (the test case: claiming Grok CLI is the poller while this chat is still alive).
5. **Draft-first means draft.** "Write and do not send" is a write op with a hold flag, never a send.
6. **Holds need dates.** A hold proposed without a date is incomplete — the gate asks for it or stamps it unresolved, never silently dateless.

## 6. Shelf mapping (with the test breath as the worked example)

| Shelf | Holds | From the test breath |
|---|---|---|
| **Semantic** | facts about the world/people | "The Seattle day is cancelled" (as a recorded fact, §5.2) |
| **Episodic** | what happened, when | the breath itself, as an event in the conversation |
| **Taxonomic** | categories, domain terms | "work order" — *refused pending definition* (§5.3) |
| **Procedural** | how we do things, rules | "draft-first: write, don't send"; "a hold needs a date"; "the poller flips only if this chat dies" |

## 7. Scope

**V1 (this build):** single operator, single project; transcript-in (finished utterances); sorter + gate running offline against transcripts first, then live; SDK writes; local trace store; wrapper-assembled context with explicit session filter; the §8 acceptance battery passing end to end.

**Non-goals for v1:** multi-user or shared projects; replacing the local markdown memory (this store sits **beside** it, per the Oct 13 Atlas-vs-Glint call); any external-state mutation (calendar, sends) — the gate records and raises, it does not act; auto-distillation in any form.

## 8. Acceptance tests (all must pass; evidence, not assertion)

1. **The breath replay.** Feed the original five-part breath (Seattle cancellation · hold-needs-date · draft-first · poller flip condition · file a work order). Expected: correct shelf sort, the §5 refusals fire, exactly one clarifying question (the filing target), no external state changed.
2. **Atomic multi-shelf commit.** An utterance spanning three shelves writes all three or none (kill the writer mid-commit; verify).
3. **Rule replacement.** State a rule, then change it. Expected: one live version — the new one — in every subsequent context.
4. **Trace hygiene.** Run a turn with tool calls; start a new conversation. Expected: no trace content in the new context; the in-turn tool loop still received its thinking.
5. **Extraction-off proof.** End a conversation containing an obvious fact; wait >5 minutes; read the shelves. Expected: nothing new arrived.
6. **Flag exclusion.** Flag a stored fact; rebuild context. Expected: the fact is absent from the prompt while still present in the store (documents §4.2's accepted residual).
7. **Session filter.** Two sessions, interleaved facts; build context for session B with the explicit filter. Expected: no session-A leakage.

## 9. Build sequence

- **Phase 0 — Store config.** Create the Mongo memory store; set extraction `enabled: []`; pin SDK 0.11.7; verify §8 test 5's precondition (idle store stays empty).
- **Phase 1 — Sorter + gate, offline.** `shelf_write` tool schema; gate rules §5 as code + tests against recorded transcripts, starting with the breath.
- **Phase 2 — Writer + trace.** SDK writer with atomic commit and replace semantics; local trace store with next-conversation wipe.
- **Phase 3 — Context builder.** Approved-facts-only assembly; flag index; explicit session filter.
- **Phase 4 — Live pilot.** One operator, one project, real interviews; §8 battery re-run live; debrief before any expansion.

## 10. Deliberate-error pass (tempting wrong versions, corrected in place)

- *"Just turn on Atlas extraction and let it fill the shelves."* Wrong — that is the ungated writer §4.1 exists to kill.
- *"Store the trace in Mongo too; it's all memory."* Wrong — §4.2: it can never be deleted and `build_context` would re-ingest it forever.
- *"Wipe the trace as soon as the turn's tools return."* Wrong — §4.4: the tool loop needs the thinking inside the turn; wipe at the *next* conversation's start.
- *"If a bad fact lands, delete it."* Wrong — there is no delete. Supersede + flag + exclude (§4.2), and keep the gate strict because prevention is the only cure.
- *"The connector can write the shelves."* Wrong — connector = record + search; shelf writes are SDK-only (§3.4).
- *"The SDK filters by session automatically."* Wrong on 0.11.7 — §4.5: the filter is explicit wrapper code.

## 11. Open items / unverified

- The Mongo gaps pass reportedly wrote `memory/research-agent-engine-memory-2026-10-19.md`; **that file is not on this VM** (checked `~/memory/`, `~/workspace/memory/`, full-tree find, 2026-10-19 04:52). This spec rests on Will's report of the three runs plus the Oct 13 walkthrough. If the research file surfaces, reconcile §4 against it before Phase 0.
- Mongo Agent Engine is public preview; API surface (especially delete/expiry) may change — re-verify §4.2 and §4.5 at Phase 0.
- Pricing/limits for the memory product at our volume: untested.
- The full non-Flash glm-5p3 exists in the Cursor catalog (Oct 16 baseline) but is untested as a sorter; not needed — Flash Max passed.

## Addendum A — GLM-5.3-Flash doc facts (Z.ai docs, read Oct 19, 2026)
- **tool_choice is `auto` only** — no forced-call mode. The sorter cannot be compelled to emit `shelf_write`. Gate consequence: **no tool call = no write**; a text reply is never parsed into a write. One re-ask with a stricter prompt is allowed; a second miss is a logged no-op.
- **Thinking cannot be disabled** on the 5.3 family (`thinking.type` supports `enabled` only). `reasoning_effort` ∈ {low, high, max}, default max. Effort mapping differs on the Coding Plan endpoint (xhigh/max→max, medium/high→high) — the wrapper records which endpoint it is on.
- **Preserved Thinking:** `thinking.clear_thinking` defaults true on the standard API (prior traces stripped) — that default IS our §4.4 posture. On the Coding Plan endpoint preservation is ON by default, so there the wrapper must explicitly set `clear_thinking: true` (or strip `reasoning_content`) at conversation start. Within a turn's tool loop, thinking blocks are returned complete, unmodified, in order, together with the tool results (interleaved thinking requirement) — §4.4's in-turn rule, now doc-cited.
