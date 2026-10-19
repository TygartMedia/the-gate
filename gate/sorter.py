"""The sorter: reads a finished utterance, proposes shelf writes.

The sorter PROPOSES; the gate disposes (SPEC.md §5). A sorter never writes
to a shelf directly. Any model that emits the shelf_write JSON described in
sorter_prompt.md can drive the gate — the protocol below is the interface,
GLM 5.3 Flash Max is just the shipped live path (the one the 2026-10-19
live interview test passed on).

Input is finished utterances only: the microphone makes text first, the
model reads text, nothing is sorted mid-sentence (SPEC.md §3.1).
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

# ---------------------------------------------------------------------------
# ProposedWrite — the shelf_write tool call, as data.
# ---------------------------------------------------------------------------

KINDS = ("fact", "rule", "term", "action", "claim", "hold")
OPS = ("add", "replace")
SCOPES = ("scoped", "global")


@dataclass
class ProposedWrite:
    shelf: str  # one of gate.shelves.SHELVES
    content: str
    op: str = "add"  # add | replace
    kind: str = "fact"  # fact | rule | term | action | claim | hold
    scope: str = "scoped"  # scoped | global — global is refused (§5.1)
    key: Optional[str] = None  # rule key; "replace" supersedes by key
    term: Optional[str] = None  # for kind="term"
    definition: Optional[str] = None  # for kind="term"; absent + unknown = question
    target_system: Optional[str] = None  # for kind="action" (calendar, email, ...)
    intent: Optional[str] = None  # e.g. "send" — never executed, draft only (§5.5)
    date: Optional[str] = None  # for kind="hold"; absent = unresolved (§5.6)
    fact_key: Optional[str] = None  # for kind="claim": runtime fact asserted about
    fact_value: Optional[str] = None  # for kind="claim": the value asserted
    # Set by the gate, not the sorter: held writes are stored, never acted
    # on; meta_note carries the gate's stamp (draft, unresolved, ...).
    hold: bool = False
    meta_note: Optional[str] = None


def proposal_from_dict(data: dict) -> ProposedWrite:
    known = {f for f in ProposedWrite.__dataclass_fields__}  # noqa: SLF001
    return ProposedWrite(**{k: v for k, v in data.items() if k in known})


class Sorter(Protocol):
    def propose(self, utterance: str) -> list[ProposedWrite]:
        ...


# ---------------------------------------------------------------------------
# ScriptedSorter — deterministic, for tests and the demo.
# Driven by a script dict: utterance -> list of proposal dicts.
# ---------------------------------------------------------------------------


class ScriptedSorter:
    def __init__(self, script: dict[str, list[dict]]):
        self.script = script

    def propose(self, utterance: str) -> list[ProposedWrite]:
        return [proposal_from_dict(d) for d in self.script.get(utterance, [])]


class KeywordSorter:
    """A tiny heuristic sorter for the CLI's ingest mode.

    Deliberately dumb — it exists so `python -m gate.cli ingest "..."` does
    something honest without an API key. Real use wants GLMSorter.
    """

    def propose(self, utterance: str) -> list[ProposedWrite]:
        text = utterance.strip()
        low = text.lower()
        out: list[ProposedWrite] = [
            # The utterance itself, as an event (SPEC.md §6).
            ProposedWrite(shelf="episodic", kind="fact",
                          content=f"Utterance recorded: {text}")
        ]
        if "cancel" in low:
            out.append(ProposedWrite(shelf="semantic", kind="fact", content=text))
        if low.startswith("rule:"):
            out.append(ProposedWrite(
                shelf="procedural", kind="rule", scope="scoped",
                key="adhoc-rule", content=text[len("rule:"):].strip()))
        if "draft" in low and "send" in low:
            out.append(ProposedWrite(
                shelf="procedural", kind="rule", scope="scoped",
                key="draft-first", content="Draft-first: write and do not send."))
        return out


# ---------------------------------------------------------------------------
# The original interview breath (2026-10-19), as a script.
# One breath, five parts: the Seattle day is cancelled · a hold needs a
# date · draft-first means write and do not send · the poller flips only
# if this chat dies · walk through filing a work order (filing target
# unknown). The script also includes what a careless sorter might propose
# alongside — a calendar action and a false runtime claim — so the gate's
# refusals are exercised, not just its approvals.
# ---------------------------------------------------------------------------

BREATH = (
    "The Seattle day is cancelled. A hold needs a date. Draft-first means "
    "write and do not send. The poller flips only if this chat dies. "
    "Walk me through filing a work order."
)

BREATH_SCRIPT: dict[str, list[dict]] = {
    BREATH: [
        # 1. The cancellation, as a recorded fact (semantic, §6).
        {"shelf": "semantic", "kind": "fact",
         "content": "The Seattle day is cancelled."},
        # 1b. The same breath as a calendar action — the gate must convert,
        # never execute (§5.2).
        {"shelf": "episodic", "kind": "action", "target_system": "calendar",
         "content": "Cancel the Seattle day on the calendar."},
        # 2. The rule about holds (procedural).
        {"shelf": "procedural", "kind": "rule", "key": "holds-need-date",
         "content": "Holds need a date."},
        # 2b. An actual hold, proposed with no date (§5.6).
        {"shelf": "procedural", "kind": "hold",
         "content": "Hold the Seattle venue booking."},
        # 3. Draft-first (procedural rule).
        {"shelf": "procedural", "kind": "rule", "key": "draft-first",
         "content": "Draft-first: write and do not send."},
        # 4. The poller condition, stated truly (procedural rule).
        {"shelf": "procedural", "kind": "rule", "key": "poller-flip",
         "content": "The poller flips only if this chat dies."},
        # 4b. The same topic stated falsely — a runtime claim the gate must
        # refuse against live runtime facts (§5.4).
        {"shelf": "procedural", "kind": "claim",
         "content": "Grok CLI is the poller now.",
         "fact_key": "poller_owner", "fact_value": "grok_cli"},
        # 5. A domain term with no definition and no known filing target —
        # the gate asks its one question (§5.3).
        {"shelf": "taxonomic", "kind": "term", "term": "work order",
         "content": "work order"},
    ]
}


# ---------------------------------------------------------------------------
# GLMSorter — the live path, via the Cursor cloud-agent REST API.
# Thin by design: POST /v1/agents, poll the run, replay the stream, parse
# the shelf_write JSON array out of the reply. Pattern mirrors the proven
# page-watch harness (direct POST + SSE replay).
# ---------------------------------------------------------------------------

CURSOR_BASE = "https://api.cursor.com"
GLM_MODEL = {
    "id": "glm-5p3-flash",
    "params": [{"id": "reasoning", "value": "max"}],
}
_PROMPT_PATH = Path(__file__).with_name("sorter_prompt.md")


class GLMSorter:
    def __init__(self, api_key: Optional[str] = None, timeout: int = 600):
        self.api_key = api_key or os.environ.get("CURSOR_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "GLMSorter needs a Cursor API key: set CURSOR_API_KEY. "
                "No key, no live sorter — use ScriptedSorter for offline work."
            )
        self.timeout = timeout
        self.prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")

    def _call(self, method: str, path: str, body: Optional[dict] = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(CURSOR_BASE + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.api_key}")
        if data:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _fetch_text(self, agent_id: str, run_id: str) -> str:
        req = urllib.request.Request(
            f"{CURSOR_BASE}/v1/agents/{agent_id}/runs/{run_id}/stream")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        text = ""
        with urllib.request.urlopen(req, timeout=300) as resp:
            event = None
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and event in ("assistant", "result"):
                    try:
                        payload = json.loads(line.split(":", 1)[1].strip())
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload.get("text"), str):
                        if event == "assistant":
                            text += payload["text"]
                        elif len(payload["text"]) > len(text):
                            text = payload["text"]
        return text

    def propose(self, utterance: str) -> list[ProposedWrite]:
        prompt = f"{self.prompt_template}\n\nUTTERANCE:\n{utterance}\n"
        created = self._call("POST", "/v1/agents", {
            "prompt": {"text": prompt},
            "model": GLM_MODEL,
            "name": "The Gate — sorter",
        })
        agent_id = created.get("id") or (created.get("agent") or {}).get("id")
        run_id = created.get("latestRunId") or created.get("runId")
        if not agent_id or not run_id:
            raise RuntimeError(f"Cursor agent launch returned no ids: {created!r}")
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            run = self._call("GET", f"/v1/agents/{agent_id}/runs/{run_id}")
            status = run.get("status")
            if status == "FINISHED":
                text = self._fetch_text(agent_id, run_id)
                return _parse_proposals(text)
            if status in ("FAILED", "CANCELLED", "EXPIRED", "ERROR"):
                raise RuntimeError(f"Sorter run ended {status}")
            time.sleep(15)
        raise RuntimeError("Sorter run timed out")


def _parse_proposals(text: str) -> list[ProposedWrite]:
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise RuntimeError(f"Sorter reply contained no JSON array: {text[:200]!r}")
    return [proposal_from_dict(d) for d in json.loads(text[start:end + 1])]
