# The Gate

**A governed memory wrapper for agent systems.** The sorter proposes; the
gate disposes; the wrapper is the only writer.

Think of it as a log cabin kit. This repo ships the logs and the structure:
the shelf data model, the gate and its refusal rules, atomic commits, the
trace lifecycle, the context builder — the load-bearing parts, opinionated
and proven. What you pick yourself is the finish work: your Mongo account
settings, the model behind the sorter, your terminology, your voice and
prompt style, your UI. Structure is ours and tested. Finishes are yours.

## Why this exists

MongoDB Agent Engine gives agents four kinds of long-term memory —
**semantic, episodic, taxonomic, procedural** (we call them *the shelves*).
It does not give them discipline. Left alone, the platform can distill a
finished conversation into "facts" and write them straight onto the
shelves, ungated — and once a fact is in long-term memory, **the current
API has no delete and no expiry**. A bad fact is forever.

So the product isn't the memory. The product is the *gate* in front of it:

- A model (the **sorter**) reads a finished utterance and *proposes* shelf
  writes as structured tool calls. It never writes.
- A deterministic **gate** judges every proposal against plain rules:
  no global law from one sentence, no state change from a breath, no
  invented definitions, no false runtime claims, sends become held drafts,
  holds need dates. At most one clarifying question per utterance.
- Only approved proposals reach the shelves, as one **atomic** batch per
  utterance, through a single writer.
- Chain-of-thought (the **trace**) lives *beside* the shelves, never in
  them, and is wiped at the start of the next conversation.
- Context is **assembled by the wrapper**, so flagged facts can be kept
  out of every prompt even though they can never be deleted.

The full design — architecture, hard constraints, gate rules, acceptance
battery — is in [SPEC.md](SPEC.md). It was written from three live agent
runs on 2026-10-19, including a live interview in which GLM 5.3 Flash Max
sorted one spoken breath across the shelves and refused exactly the parts
it should have. That breath is the demo.

## What's in the kit / what you choose

| In the kit (structure, shipped & tested) | Your choice (finishes) |
|---|---|
| The four-shelf data model (`gate/shelves.py`) | Your Mongo account, store, and project settings (`gate.toml` `[mongo]`) |
| The gate + the six refusal rules (`gate/gate.py`) | The model behind the sorter — any model emitting the `shelf_write` JSON drives it |
| Atomic per-utterance commits; replace-by-supersede; no delete, by design | Your terminology and vocabulary (domain terms are project-shared) |
| The trace lifecycle (`gate/trace.py`) | Voice, prompt style, and UI |
| The context builder with explicit session filtering (`gate/context.py`) | Per-shelf enablement and other knobs (`gate.toml` `[gate]`) |
| The reference store + the Mongo adapter seam | The plumbing edits your account needs in `gate/mongo_adapter.py` |

The sorter is a protocol (`gate/sorter.py: Sorter`), on purpose: the gate
is the interface that matters. GLM 5.3 Flash Max via the Cursor cloud-agent
API is the shipped live path because it's the one that passed the live
interview test. Anything else that emits the same JSON can drive it.

## Quickstart

Python 3.11+, standard library only. Nothing to install.

```bash
# the demo: the original interview breath, end to end
python -m gate.cli demo

# the acceptance battery
python -m unittest discover -s tests -v

# try a single utterance (tiny built-in keyword sorter, no API key needed)
python -m gate.cli ingest "Team lunch is cancelled Friday"
```

For the live sorter, set `CURSOR_API_KEY` and use `gate.sorter.GLMSorter`.
For Mongo, fill in the `[mongo]` section of `gate.toml` and hand
`MongoShelfStore` a `MongoTransport` — and read the next section first.

## Proven vs inferred

Plainly, because a gift shouldn't overclaim:

**Proven here** (in this repo, by the test battery):
- The gate and its six refusal rules, including the one-question budget.
- The reference store: atomic batches, replace-by-supersede, flag-to-
  exclude, and the structural absence of a delete.
- The trace lifecycle: returned in-turn, wiped at conversation start,
  refused by the gate as a write, absent from built context.
- The context builder: explicit session filter (no session id = excluded
  under a filter, included under `ALL_SESSIONS`), `build(None)` raises.
- The demo breath replay, end to end.

**Inferred** (written to be adjusted, NOT live-verified):
- `gate/mongo_adapter.py`. Mongo's agent-memory API is public preview and
  its exact endpoint shapes were not verified against a live account when
  this was written (SPEC §11). Every inferred specific — base URL, store /
  project ids, auth shape, endpoint paths — lives in `gate.toml`'s
  `[mongo]` section or is marked
  `# INFERRED — adjust to your account; this is the plumbing seam.`
  Its tests (against a `FakeTransport`) prove request *shape*: one
  transport call per atomic batch, supersede markers in replace payloads.
  They do not prove Mongo's live behavior. When you wire a real account,
  the edits should land in `gate.toml` and `MongoTransport` only.
- The SDK pin note (`0.11.7`) and the no-delete / no-session-id behaviors
  rest on Mongo's docs as read on 2026-10-19, plus the builder's report of
  the research runs. Re-verify at integration — the spec says so too.

## Layout

```
gate.toml            config: extraction OFF, shelf switches, [mongo] plumbing
gate/shelves.py      shelf model + protocol + LocalShelfStore (reference)
gate/sorter.py       Sorter protocol, ScriptedSorter, KeywordSorter, GLMSorter
gate/sorter_prompt.md  the sorter system prompt (shelf_write JSON contract)
gate/gate.py         the gate — SPEC §5 as code
gate/trace.py        the trace store (beside the shelves, wiped per conversation)
gate/context.py      the context builder (the only read path into a prompt)
gate/config.py       gate.toml loading + the extraction == [] assertion
gate/mongo_adapter.py  MongoTransport seam + MongoShelfStore (inferred)
gate/cli.py          demo + ingest
tests/test_gate.py   the acceptance battery + adapter shape tests
SPEC.md              the full design spec
```

## License

MIT — see [LICENSE](LICENSE). © 2026 Will Tygart / Tygart Media.
Built by Will Tygart and Glint (Tygart Media). Given freely: if the gate
discipline saves your agent from one permanent bad fact, it did its job.
