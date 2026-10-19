"""The Gate — acceptance battery (SPEC.md §8, adapted) + adapter shape tests.

Run from the repo root:  python -m unittest discover -s tests -v
Stdlib unittest only.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gate.config import MongoConfig, assert_extraction_off, load_config  # noqa: E402
from gate.context import ALL_SESSIONS, ContextBuilder  # noqa: E402
from gate.gate import Gate, entry_from_proposal  # noqa: E402
from gate.mongo_adapter import MongoShelfStore  # noqa: E402
from gate.shelves import Entry, LocalShelfStore  # noqa: E402
from gate.sorter import BREATH, BREATH_SCRIPT, ProposedWrite, ScriptedSorter  # noqa: E402
from gate.trace import TraceEntry, TraceStore  # noqa: E402

RUNTIME_FACTS = {"poller_owner": "this_chat"}


def commit(decision, store, session_id=None):
    store.write_batch([entry_from_proposal(p, session_id=session_id)
                       for p in decision.approved])


class BreathReplayTest(unittest.TestCase):
    """§8.1 — the original five-part breath, end to end."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = LocalShelfStore(Path(self.tmp) / "shelves.json")
        gate = Gate(store=self.store)
        proposals = ScriptedSorter(BREATH_SCRIPT).propose(BREATH)
        self.decision = gate.evaluate(proposals, RUNTIME_FACTS)
        commit(self.decision, self.store, session_id="interview")
        self.entries = self.store.all_entries()
        self.built = ContextBuilder(self.store).build(ALL_SESSIONS)

    def by_content(self, fragment):
        return [e for e in self.entries if fragment in e.content]

    def test_cancellation_lands_on_semantic_shelf(self):
        hits = [e for e in self.by_content("Seattle day is cancelled")
                if e.shelf == "semantic"]
        self.assertEqual(len(hits), 1)

    def test_action_converted_never_executed(self):
        self.assertEqual(len(self.decision.action_raises), 1)
        raised = self.decision.action_raises[0]
        self.assertEqual(raised["target_system"], "calendar")
        self.assertEqual(raised["status"], "raised-not-executed")
        episodic = [e for e in self.entries
                    if e.shelf == "episodic" and "NOT executed" in e.content]
        self.assertEqual(len(episodic), 1)
        # No calendar-shaped write reached any shelf.
        self.assertFalse(any(e.kind == "action" for e in self.entries))

    def test_rules_land_on_procedural_shelf(self):
        procedural = {e.content for e in self.entries if e.shelf == "procedural"}
        self.assertIn("Holds need a date.", procedural)
        self.assertIn("Draft-first: write and do not send.", procedural)
        self.assertIn("The poller flips only if this chat dies.", procedural)

    def test_unknown_term_refused_with_exactly_one_question(self):
        self.assertEqual(len(self.decision.questions), 1)
        self.assertIn("work order", self.decision.questions[0])
        self.assertFalse(any(e.shelf == "taxonomic" for e in self.entries))
        term_refusals = [r for r in self.decision.refused
                         if r.rule.startswith("§5.3")]
        self.assertEqual(len(term_refusals), 1)

    def test_false_poller_claim_refused_against_runtime_facts(self):
        claim_refusals = [r for r in self.decision.refused
                          if r.rule.startswith("§5.4")]
        self.assertEqual(len(claim_refusals), 1)
        self.assertFalse(any("Grok CLI is the poller" in e.content
                             for e in self.entries))

    def test_dateless_hold_not_cleanly_written(self):
        holds = [e for e in self.entries if e.kind == "hold"]
        self.assertEqual(len(holds), 1)
        self.assertTrue(holds[0].hold)
        self.assertEqual(holds[0].meta.get("unresolved"), "missing date")


class AtomicCommitTest(unittest.TestCase):
    """§8.2 — a batch that fails mid-write leaves zero entries."""

    def test_failed_batch_leaves_store_untouched(self):
        tmp = tempfile.mkdtemp()
        store = LocalShelfStore(Path(tmp) / "shelves.json")
        batch = [Entry(shelf=s, content=f"{s} entry", session_id="s1")
                 for s in ("semantic", "episodic", "procedural")]
        with mock.patch("gate.shelves.os.replace",
                        side_effect=OSError("killed mid-commit")):
            with self.assertRaises(OSError):
                store.write_batch(batch)
        self.assertEqual(store.all_entries(), [])


class RuleReplacementTest(unittest.TestCase):
    """§8.3 — a changed rule replaces the old one; one live version."""

    def test_replacement_supersedes(self):
        tmp = tempfile.mkdtemp()
        store = LocalShelfStore(Path(tmp) / "shelves.json")
        gate = Gate(store=store)
        v1 = ProposedWrite(shelf="procedural", kind="rule", key="draft-first",
                           content="Draft-first: ask before writing.")
        commit(gate.evaluate([v1], {}), store)
        v2 = ProposedWrite(shelf="procedural", kind="rule", key="draft-first",
                           op="replace",
                           content="Draft-first: write and do not send.")
        commit(gate.evaluate([v2], {}), store)
        built = ContextBuilder(store).build(ALL_SESSIONS)
        self.assertIn("write and do not send", built.text)
        self.assertNotIn("ask before writing", built.text)
        entries = store.all_entries()
        self.assertEqual(len(entries), 2)  # the old version stays stored…
        live = [e for e in entries if e.live]
        self.assertEqual(len(live), 1)     # …but only one is live


class TraceHygieneTest(unittest.TestCase):
    """§8.4 — trace lives beside the shelves, dies at conversation start."""

    def test_trace_lifecycle(self):
        tmp = tempfile.mkdtemp()
        trace = TraceStore(Path(tmp) / "trace.jsonl")
        store = LocalShelfStore(Path(tmp) / "shelves.json")
        secret = "TRACE-ONLY-THINKING-7f3a"
        trace.append_thinking("turn-1", secret)
        # In-turn: the tool loop can still get its thinking back.
        self.assertIn(secret, trace.get_for_turn("turn-1"))
        # The gate refuses a trace object outright — no path into a shelf.
        decision = Gate(store=store).evaluate(
            [TraceEntry(turn_id="turn-1", text=secret)], {})
        self.assertEqual(len(decision.approved), 0)
        self.assertEqual(decision.refused[0].rule, "type")
        # Built context can never contain trace text.
        built = ContextBuilder(store).build(ALL_SESSIONS)
        self.assertNotIn(secret, built.text)
        # Next conversation: wiped.
        trace.start_conversation()
        self.assertEqual(trace.get_for_turn("turn-1"), "")


class ExtractionOffTest(unittest.TestCase):
    """§8.5 — extraction stays [], and an idle store gains nothing."""

    def test_config_asserts_extraction_off(self):
        config = load_config()
        self.assertEqual(config.extraction, [])
        assert_extraction_off(config)  # must not raise

    def test_idle_store_stays_empty(self):
        tmp = tempfile.mkdtemp()
        store = LocalShelfStore(Path(tmp) / "shelves.json")
        # There is no background writer by construction: only gate-approved
        # write_batch calls add entries. An "idle wait" changes nothing.
        self.assertEqual(store.all_entries(), [])


class FlagExclusionTest(unittest.TestCase):
    """§8.6 — flagged fact: absent from context, still present in store."""

    def test_flag_excludes_without_deleting(self):
        tmp = tempfile.mkdtemp()
        store = LocalShelfStore(Path(tmp) / "shelves.json")
        entry = Entry(shelf="semantic", content="A fact we no longer trust.")
        store.write_batch([entry])
        store.flag(entry.id)
        self.assertIsNotNone(store.get(entry.id))  # still stored
        built = ContextBuilder(store).build(ALL_SESSIONS)
        self.assertNotIn("no longer trust", built.text)
        self.assertEqual(built.entry_ids, [])


class SessionFilterTest(unittest.TestCase):
    """§8.7 — explicit session filter; no-session-id entries under a filter."""

    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.store = LocalShelfStore(Path(tmp) / "shelves.json")
        self.store.write_batch([
            Entry(shelf="semantic", content="session A fact", session_id="A"),
            Entry(shelf="semantic", content="session B fact", session_id="B"),
            Entry(shelf="episodic", content="orphan episode", session_id=None),
        ])

    def test_filter_for_b_excludes_a_and_orphans(self):
        built = ContextBuilder(self.store).build("B")
        self.assertIn("session B fact", built.text)
        self.assertNotIn("session A fact", built.text)
        self.assertNotIn("orphan episode", built.text)

    def test_all_sessions_includes_orphans(self):
        built = ContextBuilder(self.store).build(ALL_SESSIONS)
        self.assertIn("orphan episode", built.text)
        self.assertIn("session A fact", built.text)

    def test_none_filter_raises(self):
        with self.assertRaises(ValueError):
            ContextBuilder(self.store).build(None)


class GateRulesExtraTest(unittest.TestCase):
    """§5.1 + the one-question budget, exercised directly."""

    def test_global_law_refused(self):
        proposal = ProposedWrite(shelf="procedural", kind="rule", scope="global",
                                 content="Everyone must always do this.")
        decision = Gate().evaluate([proposal], {})
        self.assertEqual(decision.approved, [])
        self.assertTrue(decision.refused[0].rule.startswith("§5.1"))

    def test_at_most_one_question_per_utterance(self):
        proposals = [
            ProposedWrite(shelf="taxonomic", kind="term", term="work order",
                          content="work order"),
            ProposedWrite(shelf="taxonomic", kind="term", term="shelf audit",
                          content="shelf audit"),
        ]
        decision = Gate().evaluate(proposals, {})
        self.assertEqual(len(decision.questions), 1)
        self.assertEqual(len(decision.refused), 2)  # both terms refused

    def test_send_intent_becomes_held_draft(self):
        proposal = ProposedWrite(shelf="episodic", kind="action",
                                 target_system="email", intent="send",
                                 content="Draft of the update email.")
        decision = Gate().evaluate([proposal], {})
        self.assertEqual(len(decision.approved), 1)
        self.assertTrue(decision.approved[0].hold)
        self.assertEqual(decision.action_raises, [])  # nothing raised to send

    def test_no_delete_method_exists(self):
        # The no-delete constraint is structural, not a promise (SPEC §4.2).
        self.assertFalse(hasattr(LocalShelfStore, "delete"))
        self.assertFalse(hasattr(LocalShelfStore, "remove"))
        self.assertFalse(hasattr(MongoShelfStore, "delete"))


class FakeTransport:
    """Records calls; returns canned responses. Proves request SHAPE only —
    never Mongo's live behavior (see README, Proven vs inferred)."""

    def __init__(self, search_result=None):
        self.calls = []
        self.search_result = search_result or []

    def write_entries(self, entries):
        self.calls.append(("write_entries", entries))
        return {"ok": True}

    def search_entries(self, query):
        self.calls.append(("search_entries", query))
        return self.search_result

    def flag_entry(self, entry_id):
        self.calls.append(("flag_entry", entry_id))
        return {"ok": True}


class MongoAdapterShapeTest(unittest.TestCase):
    """Adapter tests: serialization + call shape against a FakeTransport."""

    def test_batch_is_one_transport_call_with_serialized_entries(self):
        fake = FakeTransport()
        store = MongoShelfStore(fake)
        store.write_batch([
            Entry(shelf="semantic", content="fact one", session_id="s1"),
            Entry(shelf="procedural", kind="rule", key="draft-first",
                  content="Draft-first."),
        ])
        writes = [c for c in fake.calls if c[0] == "write_entries"]
        self.assertEqual(len(writes), 1)  # atomic batch = one call
        payload = writes[0][1]
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["shelf"], "semantic")
        self.assertEqual(payload[0]["content"], "fact one")
        self.assertEqual(payload[0]["session_id"], "s1")
        self.assertIn("id", payload[0])
        self.assertIn("created_at", payload[0])

    def test_replace_carries_supersede_marker_in_payload(self):
        fake = FakeTransport()
        store = MongoShelfStore(fake)
        store.write_batch([
            Entry(shelf="procedural", kind="rule", key="draft-first",
                  content="Draft-first v2.", meta={"op": "replace"}),
        ])
        payload = fake.calls[0][1]
        self.assertEqual(payload[0]["supersedes_key"], "draft-first")

    def test_flag_and_read_go_through_the_transport(self):
        canned = [{"shelf": "taxonomic", "content": "work order",
                   "kind": "term", "meta": {"term": "work order"}}]
        fake = FakeTransport(search_result=canned)
        store = MongoShelfStore(fake)
        self.assertEqual(store.known_terms(), {"work order"})
        store.flag("entry-123")
        self.assertIn(("flag_entry", "entry-123"), fake.calls)

    def test_config_carries_inferred_mongo_surfaces(self):
        config = load_config()
        self.assertIsInstance(config.mongo, MongoConfig)
        self.assertIn("0.11.7", config.mongo.sdk_pin)
        self.assertIn("{store_id}", config.mongo.write_batch_path)


if __name__ == "__main__":
    unittest.main()
