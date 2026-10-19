"""Configuration: gate.toml, loaded with stdlib tomllib.

The one hard assertion in this module: extraction must be the empty list.
Auto-distillation is the ungated writer the whole design exists to kill
(SPEC.md §4.1) — if the config ever says otherwise, startup fails loudly
rather than quietly growing a second writer.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "gate.toml"


@dataclass
class MongoConfig:
    base_url: str = ""
    store_id: str = ""
    project_id: str = ""
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    api_key_env: str = "MONGO_AGENT_MEMORY_API_KEY"
    write_batch_path: str = "/v1/stores/{store_id}/entries:batchWrite"
    search_path: str = "/v1/stores/{store_id}/entries:search"
    flag_path: str = "/v1/stores/{store_id}/entries/{entry_id}:flag"
    sdk_pin: str = ""


@dataclass
class Config:
    extraction: list = field(default_factory=list)
    session_filter: str = "explicit"
    shelves_enabled: dict = field(default_factory=dict)
    mongo: MongoConfig = field(default_factory=MongoConfig)

    def disabled_shelves(self) -> set[str]:
        return {s for s, on in self.shelves_enabled.items() if not on}


def load_config(path: str | Path | None = None) -> Config:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with cfg_path.open("rb") as fh:
        raw = tomllib.load(fh)
    gate = raw.get("gate", {})
    mongo_raw = raw.get("mongo", {})
    mongo_keys = set(MongoConfig.__dataclass_fields__)  # noqa: SLF001
    return Config(
        extraction=list(gate.get("extraction", [])),
        session_filter=gate.get("session_filter", "explicit"),
        shelves_enabled=dict(gate.get("shelves", {})),
        mongo=MongoConfig(**{k: v for k, v in mongo_raw.items() if k in mongo_keys}),
    )


def assert_extraction_off(config: Config) -> None:
    """Fail loudly unless auto-distillation is fully off (SPEC §4.1)."""
    if config.extraction != []:
        raise RuntimeError(
            f"gate.toml sets extraction={config.extraction!r}. The Gate "
            "requires extraction == []: Atlas auto-distillation writes "
            "ungated facts to the shelves and skips the gate entirely "
            "(SPEC §4.1). The wrapper is the only writer."
        )
