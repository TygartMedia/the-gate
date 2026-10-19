"""The context builder: the ONLY read path into a prompt.

Wrapper-assembled, on purpose (SPEC.md §3.6, §4.2): because the wrapper
builds context, flagged facts can be excluded even though the store can
never delete them.

Session filtering is explicit wrapper code (SPEC.md §4.5). The SDK does not
apply the live session as a filter on its own (0.11.7), and consolidated
entries may carry no session id at all — so the filter here is a REQUIRED
argument with no silent default:

- build(session_id)       -> only that session's live, unflagged entries.
                             Entries with NO session id are excluded too:
                             under a filter, unattributed memory is not
                             assumed to belong (the amnesia behavior, made
                             safe by making it visible here).
- build(ALL_SESSIONS)     -> deliberate unfiltered build.
- build(None)             -> raises. There is no quiet "all".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class _AllSessions:
    def __repr__(self) -> str:
        return "ALL_SESSIONS"


ALL_SESSIONS = _AllSessions()


@dataclass
class BuiltContext:
    text: str
    entry_ids: list[str] = field(default_factory=list)


class ContextBuilder:
    def __init__(self, store):
        self.store = store

    def build(self, session_filter: Optional[str] | _AllSessions) -> BuiltContext:
        if session_filter is None:
            raise ValueError(
                "session_filter is required: pass a session id, or "
                "ALL_SESSIONS for a deliberate unfiltered build. "
                "There is no silent default (SPEC §4.5)."
            )
        filtering = session_filter is not ALL_SESSIONS
        chosen = []
        for entry in self.store.all_entries():
            if entry.flagged:
                continue  # §4.2: bytes stay in the store, never in a prompt
            if not entry.live:
                continue  # superseded by a newer write
            if filtering and entry.session_id != session_filter:
                continue  # includes session_id=None under a filter (§4.5)
            chosen.append(entry)
        lines: list[str] = []
        current_shelf = None
        for entry in sorted(chosen, key=lambda e: (e.shelf, e.created_at)):
            if entry.shelf != current_shelf:
                current_shelf = entry.shelf
                lines.append(f"## {current_shelf}")
            stamp = " [HELD]" if entry.hold else ""
            lines.append(f"- ({entry.kind}) {entry.content}{stamp}")
        return BuiltContext(
            text="\n".join(lines),
            entry_ids=[e.id for e in chosen],
        )
