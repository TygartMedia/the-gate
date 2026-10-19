"""Shelf storage: the four long-term memory shelves and the store protocol.

The shelves mirror MongoDB Agent Engine's four long-term memory types:
semantic, episodic, taxonomic, procedural (SPEC.md §1, §6).

One design constraint is deliberate and load-bearing: **there is no delete
method anywhere in this module.** Mongo's long-term memory API has no
client delete and no expiry (SPEC.md §4.2), so this reference store mirrors
that constraint instead of pretending it away. Remediation for a bad entry
is supersede + flag + exclusion at context-build time — the bytes stay,
they just never reach a prompt again.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

SHELVES = ("semantic", "episodic", "taxonomic", "procedural")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Entry:
    """One item on a shelf. Written once; never deleted."""

    shelf: str
    content: str
    kind: str = "fact"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    # Some entries legitimately have no session id — Mongo's consolidated
    # episodes are stored with none (SPEC.md §4.5). The context builder,
    # not the store, decides what that means under a session filter.
    session_id: Optional[str] = None
    # Set when a later "replace" write supersedes this entry.
    superseded_by: Optional[str] = None
    # Wrapper-side flag: flagged entries are excluded from built context
    # but remain in the store (SPEC.md §4.2). Flagging is not deleting.
    flagged: bool = False
    # Rule key: a "replace" op supersedes the prior live entry with the
    # same key on the same shelf.
    key: Optional[str] = None
    # Held writes (e.g. drafts) are stored, never acted on (SPEC.md §5.5).
    hold: bool = False
    created_at: str = field(default_factory=_now)
    meta: dict = field(default_factory=dict)

    @property
    def live(self) -> bool:
        return self.superseded_by is None


def entry_to_dict(entry: Entry) -> dict:
    return asdict(entry)


def entry_from_dict(data: dict) -> Entry:
    known = {f for f in Entry.__dataclass_fields__}  # noqa: SLF001
    return Entry(**{k: v for k, v in data.items() if k in known})


@runtime_checkable
class ShelfStore(Protocol):
    """The only write path to the shelves. Implementations: LocalShelfStore
    (reference, in this module) and MongoShelfStore (gate/mongo_adapter.py).

    Note what is NOT here: no delete, no purge, no expire. By design.
    """

    def write_batch(self, entries: list[Entry]) -> None:
        """Atomically write a batch (one utterance's worth): all or none."""
        ...

    def all_entries(self) -> list[Entry]:
        ...

    def get(self, entry_id: str) -> Optional[Entry]:
        ...

    def flag(self, entry_id: str) -> None:
        """Flag an entry for exclusion from context. Never deletes."""
        ...


class LocalShelfStore:
    """JSON-file backed reference store. Stdlib only.

    Atomicity: every mutation serializes the full new state to a temp file
    in the same directory and os.replace()s it over the old file, so a
    failure mid-batch leaves the previous state untouched.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._persist([])

    # -- internals -------------------------------------------------------
    def _load(self) -> list[Entry]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [entry_from_dict(d) for d in raw.get("entries", [])]

    def _persist(self, entries: list[Entry]) -> None:
        payload = json.dumps(
            {"entries": [entry_to_dict(e) for e in entries]},
            ensure_ascii=False,
            indent=2,
        )
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # -- protocol --------------------------------------------------------
    def write_batch(self, entries: list[Entry]) -> None:
        current = self._load()
        by_key = {
            (e.shelf, e.key): e
            for e in current
            if e.live and e.key is not None
        }
        for entry in entries:
            if entry.meta.get("op") == "replace" and entry.key is not None:
                prior = by_key.get((entry.shelf, entry.key))
                if prior is not None and prior.id != entry.id:
                    prior.superseded_by = entry.id
            current.append(entry)
        self._persist(current)

    def all_entries(self) -> list[Entry]:
        return self._load()

    def get(self, entry_id: str) -> Optional[Entry]:
        for entry in self._load():
            if entry.id == entry_id:
                return entry
        return None

    def flag(self, entry_id: str) -> None:
        entries = self._load()
        for entry in entries:
            if entry.id == entry_id:
                entry.flagged = True
        self._persist(entries)

    def known_terms(self) -> set[str]:
        """Terms already defined on the taxonomic shelf (gate rule §5.3)."""
        return {
            e.meta["term"]
            for e in self._load()
            if e.shelf == "taxonomic" and e.meta.get("term")
        }
