"""The Gate — a governed memory wrapper.

The sorter proposes; the gate disposes; the wrapper is the only writer.
See README.md and SPEC.md.
"""

from .config import Config, assert_extraction_off, load_config
from .context import ALL_SESSIONS, BuiltContext, ContextBuilder
from .gate import Decision, Gate, Refusal, entry_from_proposal
from .shelves import Entry, LocalShelfStore, ShelfStore
from .sorter import (
    BREATH,
    BREATH_SCRIPT,
    GLMSorter,
    KeywordSorter,
    ProposedWrite,
    ScriptedSorter,
    Sorter,
)
from .trace import TraceEntry, TraceStore

__version__ = "0.1.0"

__all__ = [
    "ALL_SESSIONS",
    "BREATH",
    "BREATH_SCRIPT",
    "BuiltContext",
    "Config",
    "ContextBuilder",
    "Decision",
    "Entry",
    "GLMSorter",
    "Gate",
    "KeywordSorter",
    "LocalShelfStore",
    "ProposedWrite",
    "Refusal",
    "ScriptedSorter",
    "ShelfStore",
    "Sorter",
    "TraceEntry",
    "TraceStore",
    "assert_extraction_off",
    "entry_from_proposal",
    "load_config",
]
