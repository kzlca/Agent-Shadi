from __future__ import annotations

from typing import Iterable
from .contracts import SourceAdapter, SourceKind, SourceSpec


class SourceRegistry:
    """Small explicit adapter registry; no platform-name branching in the core."""
    def __init__(self, adapters: Iterable[SourceAdapter] = ()) -> None:
        self._by_kind: dict[SourceKind, SourceAdapter] = {}
        self._by_name: dict[str, SourceAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: SourceAdapter) -> None:
        name = str(adapter.name).strip().lower()
        if not name:
            raise ValueError("Adapter name cannot be empty.")
        if name in self._by_name:
            raise ValueError(f"Adapter already registered: {name}")
        for kind in adapter.kinds:
            if kind in self._by_kind:
                raise ValueError(f"An adapter is already registered for {kind.value}.")
        self._by_name[name] = adapter
        for kind in adapter.kinds:
            self._by_kind[kind] = adapter

    def for_source(self, source: SourceSpec) -> SourceAdapter:
        try:
            return self._by_kind[source.kind]
        except KeyError as exc:
            raise LookupError(f"No adapter is registered for source kind '{source.kind.value}'.") from exc

    def by_name(self, name: str) -> SourceAdapter:
        try:
            return self._by_name[name.strip().lower()]
        except KeyError as exc:
            raise LookupError(f"Unknown source adapter: {name}") from exc

    def describe(self) -> list[dict[str, object]]:
        return [
            {"name": adapter.name, "source_kinds": sorted(kind.value for kind in adapter.kinds)}
            for adapter in self._by_name.values()
        ]
