# RESULTS — The Gate v0.1.0 build

Built 2026-10-19 from `SPEC.md` (the Gate build spec, copied in from
`~/workspace/out/agent-engine-memory-2026-10-19/BUILD-SPEC.md`).

## What was built

The full package per the brief, stdlib-only Python 3.12:

- `gate/shelves.py` — `Entry`, `ShelfStore` protocol, `LocalShelfStore`
  (JSON file, temp-write + `os.replace` atomicity, replace-by-key
  supersede, flag-without-delete, and **no delete method anywhere**).
- `gate/sorter.py` — `ProposedWrite`, `Sorter` protocol, `ScriptedSorter`
  (with the original breath as `BREATH_SCRIPT`), `KeywordSorter` (CLI
  ingest), and a thin `GLMSorter` over the Cursor cloud-agent REST API
  (POST `/v1/agents`, model `glm-5p3-flash`, reasoning `max`, run polling
  + SSE stream replay, mirroring the proven page-watch harness pattern;
  key from `CURSOR_API_KEY`, clear `RuntimeError` when unset — verified).
- `gate/sorter_prompt.md` — the `shelf_write` JSON contract + shelf
  definitions + annotation rules the gate judges by.
- `gate/gate.py` — SPEC §5 as code: §5.1 global-law refusal, §5.2 action
  conversion (episodic record + raised-action record, never executed),
  §5.3 undefined-term → the one question (budget enforced; overflow
  becomes refusals-with-reason), §5.4 runtime-claim check against
  caller-supplied facts (dict or callable; unknown facts refused as
  unverifiable), §5.5 send intent → held draft, §5.6 dateless hold →
  written stamped UNRESOLVED and held. Plus type enforcement: non-
  `ProposedWrite` objects (e.g. trace entries) are refused on sight.
- `gate/trace.py` — `TraceStore`: JSONL beside the shelves, in-turn
  retrieval, `start_conversation()` wipe.
- `gate/context.py` — `ContextBuilder.build(session_filter)`: `None`
  raises; `ALL_SESSIONS` sentinel for deliberate unfiltered builds;
  flagged + superseded excluded; no-session-id entries excluded under a
  session filter.
- `gate/config.py` + `gate.toml` — `extraction = []` asserted at startup
  (demo fails loudly otherwise), per-shelf enablement switches, session-
  filter strictness knob, sdk-pin note, and the `[mongo]` section.
- `gate/mongo_adapter.py` — **real adapter per Will's steer** (replaces the
  original brief's NotImplementedError skeleton): `MongoTransport` isolates
  every inferred endpoint call behind config; `MongoShelfStore` implements
  the protocol over it — batch write = one transport call, replace carries
  a `supersedes_key` payload marker, flag is a write not a removal. Every
  inferred surface is commented `# INFERRED — adjust to your account; this
  is the plumbing seam.` (11 occurrences across the adapter + gate.toml).
- `gate/cli.py` — `python -m gate.cli demo` and `ingest`; both run.
- `README.md`, `SPEC.md`, `LICENSE` (MIT, © 2026 Will Tygart / Tygart Media).

## Test command and actual output

```
$ cd ~/workspace/the-gate && python -m unittest discover -s tests -v
test_failed_batch_leaves_store_untouched (test_gate.AtomicCommitTest.test_failed_batch_leaves_store_untouched) ... ok
test_action_converted_never_executed (test_gate.BreathReplayTest.test_action_converted_never_executed) ... ok
test_cancellation_lands_on_semantic_shelf (test_gate.BreathReplayTest.test_cancellation_lands_on_semantic_shelf) ... ok
test_dateless_hold_not_cleanly_written (test_gate.BreathReplayTest.test_dateless_hold_not_cleanly_written) ... ok
test_false_poller_claim_refused_against_runtime_facts (test_gate.BreathReplayTest.test_false_poller_claim_refused_against_runtime_facts) ... ok
test_rules_land_on_procedural_shelf (test_gate.BreathReplayTest.test_rules_land_on_procedural_shelf) ... ok
test_unknown_term_refused_with_exactly_one_question (test_gate.BreathReplayTest.test_unknown_term_refused_with_exactly_one_question) ... ok
test_config_asserts_extraction_off (test_gate.ExtractionOffTest.test_config_asserts_extraction_off) ... ok
test_idle_store_stays_empty (test_gate.ExtractionOffTest.test_idle_store_stays_empty) ... ok
test_flag_excludes_without_deleting (test_gate.FlagExclusionTest.test_flag_excludes_without_deleting) ... ok
test_at_most_one_question_per_utterance (test_gate.GateRulesExtraTest.test_at_most_one_question_per_utterance) ... ok
test_global_law_refused (test_gate.GateRulesExtraTest.test_global_law_refused) ... ok
test_no_delete_method_exists (test_gate.GateRulesExtraTest.test_no_delete_method_exists) ... ok
test_send_intent_becomes_held_draft (test_gate.GateRulesExtraTest.test_send_intent_becomes_held_draft) ... ok
test_batch_is_one_transport_call_with_serialized_entries (test_gate.MongoAdapterShapeTest.test_batch_is_one_transport_call_with_serialized_entries) ... ok
test_config_carries_inferred_mongo_surfaces (test_gate.MongoAdapterShapeTest.test_config_carries_inferred_mongo_surfaces) ... ok
test_flag_and_read_go_through_the_transport (test_gate.MongoAdapterShapeTest.test_flag_and_read_go_through_the_transport) ... ok
test_replace_carries_supersede_marker_in_payload (test_gate.MongoAdapterShapeTest.test_replace_carries_supersede_marker_in_payload) ... ok
test_replacement_supersedes (test_gate.RuleReplacementTest.test_replacement_supersedes) ... ok
test_all_sessions_includes_orphans (test_gate.SessionFilterTest.test_all_sessions_includes_orphans) ... ok
test_filter_for_b_excludes_a_and_orphans (test_gate.SessionFilterTest.test_filter_for_b_excludes_a_and_orphans) ... ok
test_none_filter_raises (test_gate.SessionFilterTest.test_none_filter_raises) ... ok
test_trace_lifecycle (test_gate.TraceHygieneTest.test_trace_lifecycle) ... ok

----------------------------------------------------------------------
Ran 23 tests in 0.019s

OK
```

All seven SPEC §8 tests, adapted, are in there (breath replay split into
six assertions; atomicity forced via a patched `os.replace`; §8.5's
five-minute idle wait is represented structurally — there is no background
writer by construction, and the config assertion is the live check), plus
four Mongo adapter shape tests against a `FakeTransport`.

The demo (`python -m gate.cli demo`) was also run and verified: the breath
produces 6 writes, 2 refusals (§5.4 false poller claim, §5.3 undefined
term), 1 raised calendar action, exactly 1 question, the dateless hold
stamped UNRESOLVED, and the trace wiped at conversation start.

## Left incomplete, honestly

- **GLMSorter is not live-run.** No `CURSOR_API_KEY` was spent from this
  seat; the class follows the proven page-watch harness pattern and its
  no-key error path is verified, but no real sort was executed. First live
  run should replay `BREATH` and diff against `BREATH_SCRIPT`.
- **MongoShelfStore is inferred plumbing, never pointed at a real
  account** — by design and by label (see README, "Proven vs inferred").
  The FakeTransport tests prove serialization and call shape only.
- **§8.5's literal >5-minute idle soak** was not performed against a live
  Mongo store (there is no account wired up); the local equivalent —
  no-writer-by-construction + startup assertion — is what the tests cover.
- `KeywordSorter` is a demo convenience, deliberately dumb; it is not a
  sorter anyone should ship behind the gate.
