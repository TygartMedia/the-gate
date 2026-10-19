"""The trace: per-turn chain-of-thought, kept BESIDE the shelves.

Two rules, both load-bearing (SPEC.md §4.2, §4.4):

1. Trace content never enters the shelf store. Mongo long-term memory has
   no delete; a trace stored there would be pulled back into prompts by
   context building, forever. This module's entries are a distinct type
   (TraceEntry), and the gate refuses any non-ProposedWrite object — there
   is no API path from here into a shelf.
2. Trace lifetime is the turn. The tool loop needs the thinking returned
   WITH the tool result inside the same turn, so wiping mid-turn would
   make the hands worse. Instead: start_conversation() wipes the trace.
3. Endpoint default to know (SPEC Addendum A): on Z.ai's standard API,
   thinking.clear_thinking defaults to true — prior traces are stripped,
   which is this module's posture. On the Coding Plan endpoint, Preserved
   Thinking is ON by default; a wrapper running there must explicitly set
   clear_thinking: true at conversation start, or this wipe is undone by
   the endpoint replaying the trace back in.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TraceEntry:
    turn_id: str
    text: str


class TraceStore:
    """A JSONL file that lives beside the shelf file, never inside it."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def append_thinking(self, turn_id: str, text: str) -> None:
        line = json.dumps({"turn_id": turn_id, "text": text}, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def get_for_turn(self, turn_id: str) -> str:
        """The turn's thinking — so the caller can return it with the tool
        result inside the same turn, as the tool loop expects."""
        parts = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            item = json.loads(raw)
            if item.get("turn_id") == turn_id:
                parts.append(item.get("text", ""))
        return "\n".join(parts)

    def start_conversation(self) -> None:
        """Wipe the trace. Called at the START of a new conversation —
        never mid-turn (SPEC.md §4.4). Atomic replace, same as the shelves."""
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            os.close(fd)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
