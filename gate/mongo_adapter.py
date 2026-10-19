"""MongoShelfStore: the Gate's shelves, backed by MongoDB Agent Engine memory.

HONEST LABELING — read before trusting a line of this file.

The gate, the rules, the local reference store, and the test battery are
PROVEN (tests/test_gate.py). This adapter is INFERRED plumbing: Mongo's
agent-memory API is public preview and the exact endpoint shapes were not
live-verified when this was written (SPEC.md §11). So this file is built
the way harnesses should be built: every inferred specific — base URL,
store/project ids, auth shape, endpoint paths — comes from the [mongo]
section of gate.toml, and every inferred surface is marked. A close match
plus small plumbing edits beats a perfect-on-paper stub. When you wire
this to a real account, the edits should all land in gate.toml and in
MongoTransport below — nothing else in the package needs to change.

Structure:
- MongoTransport isolates EVERY call to the inferred API. It is the seam.
- MongoShelfStore speaks only to the transport, in shelf-model terms.
- There is no delete anywhere here either — the store mirrors Mongo's
  own constraint (SPEC §4.2). Flagging is a write, not a removal.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Optional

from .config import MongoConfig
from .shelves import Entry, entry_from_dict, entry_to_dict


class MongoTransport:
    """One class, every inferred endpoint call. Adjust here + gate.toml."""

    def __init__(self, config: MongoConfig, api_key: Optional[str] = None):
        self.config = config
        self.api_key = api_key or os.environ.get(config.api_key_env, "")

    # -- plumbing --------------------------------------------------------
    def _url(self, path_template: str, **subs: str) -> str:
        # INFERRED — adjust to your account; this is the plumbing seam.
        path = path_template.format(store_id=self.config.store_id, **subs)
        return self.config.base_url.rstrip("/") + path

    def _request(self, method: str, url: str, payload: Optional[dict]) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if self.api_key:
            # INFERRED — adjust to your account; this is the plumbing seam.
            req.add_header(
                self.config.auth_header,
                f"{self.config.auth_scheme} {self.api_key}".strip(),
            )
        if data:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}

    # -- inferred endpoints ------------------------------------------------
    def write_entries(self, entries: list[dict]) -> dict:
        """One batch call for one utterance's entries — atomicity is the
        batch (SPEC §4.3): the whole list goes in a single request."""
        # INFERRED — adjust to your account; this is the plumbing seam.
        url = self._url(self.config.write_batch_path)
        return self._request("POST", url, {"entries": entries})

    def search_entries(self, query: dict) -> list[dict]:
        """The read seam: used both for context building and for fetching
        single entries. Shape assumed: response carries an entry list."""
        # INFERRED — adjust to your account; this is the plumbing seam.
        url = self._url(self.config.search_path)
        resp = self._request("POST", url, query or {})
        return resp.get("entries", [])

    def flag_entry(self, entry_id: str) -> dict:
        """Flag = a write that marks the entry; the entry remains stored
        and the context builder excludes it (SPEC §4.2)."""
        # INFERRED — adjust to your account; this is the plumbing seam.
        url = self._url(self.config.flag_path, entry_id=entry_id)
        return self._request("POST", url, {"flagged": True})


def _serialize(entry: Entry) -> dict:
    """Entry -> wire payload. A replace op carries its supersede marker in
    the payload: the key of the rule it replaces, so the far side (or a
    reconciling reader) can link old -> new without a delete."""
    data = entry_to_dict(entry)
    if entry.meta.get("op") == "replace" and entry.key is not None:
        data["supersedes_key"] = entry.key
    return data


class MongoShelfStore:
    """ShelfStore protocol over MongoTransport.

    Deliberately no delete method — same as the reference store, same as
    the underlying product (SPEC §4.2).
    """

    def __init__(self, transport: MongoTransport):
        self.transport = transport

    def write_batch(self, entries: list[Entry]) -> None:
        # The whole batch goes in ONE transport call (SPEC §4.3). Replace
        # semantics travel as payload markers (supersedes_key, see
        # _serialize): the reader side links old -> new by rule key, the
        # same reconciliation the context builder applies locally.
        payload = [_serialize(e) for e in entries]
        self.transport.write_entries(payload)

    def all_entries(self) -> list[Entry]:
        return [entry_from_dict(d) for d in self.transport.search_entries({})]

    def get(self, entry_id: str) -> Optional[Entry]:
        for entry in self.all_entries():
            if entry.id == entry_id:
                return entry
        return None

    def flag(self, entry_id: str) -> None:
        self.transport.flag_entry(entry_id)

    def known_terms(self) -> set[str]:
        return {
            e.meta["term"]
            for e in self.all_entries()
            if e.shelf == "taxonomic" and e.meta.get("term")
        }
