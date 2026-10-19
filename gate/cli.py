"""Demo CLI for The Gate.

    python -m gate.cli demo                 the original interview breath,
                                            sorted, gated, written, read back
    python -m gate.cli ingest "<utterance>" a single utterance through a
                                            tiny keyword sorter (no API key)

The demo asserts the config first: if gate.toml ever enables extraction,
it fails loudly before anything is sorted (SPEC §4.1).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from .config import assert_extraction_off, load_config
from .context import ALL_SESSIONS, ContextBuilder
from .gate import Gate, entry_from_proposal
from .shelves import LocalShelfStore
from .sorter import BREATH, BREATH_SCRIPT, KeywordSorter, ScriptedSorter
from .trace import TraceStore

RUNTIME_FACTS = {"poller_owner": "this_chat"}


def _print_decision(decision) -> None:
    print("\n— gate decision —")
    for p in decision.approved:
        stamp = " [HELD]" if p.hold else ""
        note = f" ({p.meta_note})" if p.meta_note else ""
        print(f"  WRITE  [{p.shelf}/{p.kind}] {p.content}{stamp}{note}")
    for r in decision.refused:
        print(f"  REFUSE [{r.rule}] {r.proposal.content} — {r.reason}")
    for raised in decision.action_raises:
        print(f"  RAISED  {raised['action']} -> {raised['target_system']} "
              f"({raised['status']})")
    for q in decision.questions:
        print(f"  ASK     {q}")


def _run_pipeline(utterance, sorter, store, session_id="demo"):
    gate = Gate(store=store)
    proposals = sorter.propose(utterance)
    print("— proposals —")
    for p in proposals:
        print(f"  [{p.shelf}/{p.kind}] {p.content}")
    decision = gate.evaluate(proposals, RUNTIME_FACTS)
    _print_decision(decision)
    entries = [entry_from_proposal(p, session_id=session_id)
               for p in decision.approved]
    if entries:
        store.write_batch(entries)  # one atomic batch for the utterance
    return decision


def demo() -> int:
    config = load_config()
    assert_extraction_off(config)  # fail loudly, before anything else
    print("config: extraction == [] ✓ (auto-distillation off, SPEC §4.1)")
    tmp = Path(tempfile.mkdtemp(prefix="the-gate-demo-"))
    store = LocalShelfStore(tmp / "shelves.json")
    trace = TraceStore(tmp / "trace.jsonl")

    print(f'\nutterance: "{BREATH}"')
    trace.append_thinking("turn-1", "sorting one breath across four shelves…")
    _run_pipeline(BREATH, ScriptedSorter(BREATH_SCRIPT), store)

    print("\n— shelves now hold —")
    for e in store.all_entries():
        print(f"  [{e.shelf}/{e.kind}] {e.content}"
              f"{' [HELD]' if e.hold else ''}"
              f"{' meta=' + str(e.meta) if e.meta.get('unresolved') else ''}")

    built = ContextBuilder(store).build(ALL_SESSIONS)
    print("\n— built context (ALL_SESSIONS) —")
    print(built.text)
    print(f"\n({len(built.entry_ids)} entries in context)")

    print(f'\ntrace this turn: "{trace.get_for_turn("turn-1")}"')
    trace.start_conversation()
    print(f'trace after start_conversation(): "{trace.get_for_turn("turn-1")}" '
          "(wiped — SPEC §4.4)")
    print(f"\ndemo state (throwaway): {tmp}")
    return 0


def ingest(utterance: str) -> int:
    config = load_config()
    assert_extraction_off(config)
    state = Path.cwd() / "gate-state"
    store = LocalShelfStore(state / "shelves.json")
    print(f'utterance: "{utterance}"')
    _run_pipeline(utterance, KeywordSorter(), store, session_id="cli")
    built = ContextBuilder(store).build(ALL_SESSIONS)
    print("\n— built context (ALL_SESSIONS) —")
    print(built.text)
    print(f"\nstate: {state}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["demo"]:
        return demo()
    if argv[:1] == ["ingest"] and len(argv) == 2:
        return ingest(argv[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
