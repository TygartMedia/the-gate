"""The gate: deterministic rules between a sorter's proposals and the shelves.

The sorter proposes; the gate disposes (SPEC.md §5). Every rule here was
demonstrated live in the 2026-10-19 interview test before it was code —
the refusals are the product.

One more rule, enforced by type: the gate accepts ProposedWrite objects
only. Trace objects (gate.trace.TraceEntry) are a different type and are
refused on sight — chain-of-thought can never become a shelf write through
this API (SPEC.md §4.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Optional, Union

from .shelves import Entry
from .sorter import ProposedWrite

RuntimeFacts = Union[dict, Callable[[str], Optional[str]], None]


@dataclass
class Refusal:
    proposal: ProposedWrite
    rule: str
    reason: str


@dataclass
class Decision:
    approved: list[ProposedWrite] = field(default_factory=list)
    refused: list[Refusal] = field(default_factory=list)
    # AT MOST ONE question per utterance (§5.3). Rules that want to ask
    # after the budget is spent become refusals-with-reason instead.
    questions: list[str] = field(default_factory=list)
    # Actions are never executed; they are returned here as raised records
    # for whatever channel actually owns the action (§5.2).
    action_raises: list[dict] = field(default_factory=list)


def _runtime_value(facts: RuntimeFacts, key: Optional[str]) -> Optional[str]:
    if facts is None or key is None:
        return None
    if callable(facts):
        return facts(key)
    return facts.get(key)


class Gate:
    def __init__(self, store=None, disabled_shelves: Optional[set[str]] = None):
        # The store (optional) is read for one thing only: which taxonomic
        # terms are already known (§5.3). It is never written by the gate.
        self.store = store
        self.disabled_shelves = disabled_shelves or set()

    # -- public ------------------------------------------------------------
    def evaluate(
        self,
        proposals: list,
        runtime_facts: RuntimeFacts = None,
    ) -> Decision:
        decision = Decision()
        known_terms = self._known_terms(runtime_facts)
        for proposal in proposals:
            self._evaluate_one(proposal, runtime_facts, known_terms, decision)
        return decision

    # -- internals -----------------------------------------------------------
    def _known_terms(self, runtime_facts: RuntimeFacts) -> set[str]:
        terms: set[str] = set()
        if self.store is not None and hasattr(self.store, "known_terms"):
            terms |= self.store.known_terms()
        extra = _runtime_value(runtime_facts, "known_terms")
        if extra:
            terms |= set(extra.split(",")) if isinstance(extra, str) else set(extra)
        return terms

    def _evaluate_one(self, p, runtime_facts, known_terms, d: Decision) -> None:
        # Type enforcement: only ProposedWrite may become a shelf write.
        # A trace object (or anything else) stops here.
        if not isinstance(p, ProposedWrite):
            d.refused.append(Refusal(
                p, "type",
                f"gate accepts ProposedWrite only, got {type(p).__name__}; "
                "trace content is never a shelf write (SPEC §4.2)"))
            return

        if p.shelf in self.disabled_shelves:
            d.refused.append(Refusal(
                p, "shelf-disabled",
                f"shelf '{p.shelf}' is disabled in config; write refused"))
            return

        # §5.1 — no global law from one sentence.
        if p.scope == "global":
            d.refused.append(Refusal(
                p, "§5.1 no-global-law",
                "a single utterance cannot mint a global law; "
                "re-propose it scoped and let it earn scope"))
            return

        # §5.5 — send intent: approved only as a draft write on hold.
        # Checked before the generic action rule: a send is an action that
        # gets one specific fate — drafted, held, never sent.
        if p.intent == "send":
            d.approved.append(replace(p, hold=True, meta_note="draft — held, not sent"))
            return

        # §5.2 — no state change from a breath. Actions are converted to a
        # recorded episodic fact + a raised-action record. Never executed.
        if p.kind == "action":
            d.approved.append(ProposedWrite(
                shelf="episodic", kind="fact",
                content=f"{p.content} (raised from an utterance; NOT executed)"))
            d.action_raises.append({
                "action": p.content,
                "target_system": p.target_system,
                "status": "raised-not-executed",
            })
            return

        # §5.3 — no invented definitions. Unknown term, no definition:
        # ask the one question (or refuse if the question budget is spent).
        if p.kind == "term":
            if p.definition or (p.term and p.term in known_terms):
                d.approved.append(p)
            elif len(d.questions) == 0:
                d.questions.append(
                    f"Before anything is filed under "
                    f"'{p.term or p.content}': what is it — and where does "
                    f"one actually file?")
                d.refused.append(Refusal(
                    p, "§5.3 undefined-term",
                    "term unknown and no definition given; held pending "
                    "the answer to the question above"))
            else:
                d.refused.append(Refusal(
                    p, "§5.3 undefined-term",
                    "term unknown and no definition given; the one-"
                    "question budget for this utterance is already spent"))
            return

        # §5.4 — no false runtime claims. Checked against live facts the
        # caller supplies; unknown facts are unverifiable, also refused.
        if p.kind == "claim":
            actual = _runtime_value(runtime_facts, p.fact_key)
            if actual is None:
                d.refused.append(Refusal(
                    p, "§5.4 unverifiable-claim",
                    f"runtime fact '{p.fact_key}' was not supplied; "
                    "the claim cannot be checked, so it is not written"))
            elif actual != p.fact_value:
                d.refused.append(Refusal(
                    p, "§5.4 false-runtime-claim",
                    f"claim asserts {p.fact_key}={p.fact_value!r} but the "
                    f"live value is {actual!r}"))
            else:
                d.approved.append(p)
            return

        # §5.6 — holds need dates. A dateless hold is written stamped
        # unresolved and held; it is never a clean hold. (Stamped, not
        # asked: the question budget belongs to §5.3.)
        if p.kind == "hold" and not p.date:
            d.approved.append(replace(
                p, hold=True, meta_note="UNRESOLVED — hold proposed with no date"))
            return

        d.approved.append(p)


def entry_from_proposal(p: ProposedWrite, session_id: Optional[str] = None) -> Entry:
    """Convert an APPROVED proposal into a shelf entry.

    Only call this on Decision.approved — converting a refused proposal is
    how ungated facts are born.
    """
    meta: dict = {"op": p.op}
    if p.term:
        meta["term"] = p.term
    if p.definition:
        meta["definition"] = p.definition
    note = getattr(p, "meta_note", None)
    if note:
        meta["note"] = note
        if note.startswith("UNRESOLVED"):
            meta["unresolved"] = "missing date"
    return Entry(
        shelf=p.shelf,
        content=p.content,
        kind=p.kind,
        session_id=session_id,
        key=p.key,
        hold=getattr(p, "hold", False),
        meta=meta,
    )
