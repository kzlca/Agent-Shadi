"""Source-neutral contracts for Agent Shadi's acquisition layer.

A source is anything that can provide content: a rendered browser page, a file,
pasted text, an API response, a database export, or a future connector.  The
acquisition layer preserves provenance and does not assume that every item is
a chat message.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit
import hashlib
import json


class SourceKind(str, Enum):
    BROWSER = "browser"
    FILE = "file"
    TEXT = "text"
    HTTP = "http"
    API = "api"
    DATABASE = "database"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SourceSpec:
    """User-supplied source identity and non-secret acquisition settings."""
    id: str
    kind: SourceKind
    label: str
    uri: str = ""
    content_type: str = ""
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("A source needs a stable id.")
        if not self.label.strip():
            raise ValueError("A source needs a human-readable label.")
        if self.uri:
            parsed = urlsplit(self.uri)
            if parsed.scheme and parsed.scheme not in {"http", "https", "file", "mailto"}:
                raise ValueError("Unsupported source URI scheme.")
            if parsed.username or parsed.password:
                raise ValueError("Source URIs must not contain embedded credentials.")


@dataclass
class SourceItem:
    """One captured content unit, regardless of whether it is a post or row."""
    content: str
    source_id: str
    source_label: str
    source_uri: str = ""
    item_id: str = ""
    item_type: str = "document"
    published_at: str | None = None
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    author: str = ""
    title: str = ""
    content_type: str = "text/plain"
    attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        normalized = " ".join((self.content or "").casefold().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["fingerprint"] = self.fingerprint
        return value


@dataclass
class CaptureBatch:
    source: SourceSpec
    items: list[SourceItem] = field(default_factory=list)
    complete: bool = False
    cursor: str | None = None
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "CaptureBatch":
        seen: set[str] = set()
        unique: list[SourceItem] = []
        for item in self.items:
            if not isinstance(item, SourceItem):
                raise TypeError("Adapters must return SourceItem instances.")
            if item.source_id != self.source.id:
                raise ValueError("Captured item source_id does not match its batch source.")
            if not item.content or not item.content.strip():
                continue
            fp = item.fingerprint
            if fp and fp not in seen:
                seen.add(fp)
                unique.append(item)
        self.items = unique
        return self

    def summary(self) -> dict[str, Any]:
        return {
            "source_id": self.source.id,
            "source_kind": self.source.kind.value,
            "source_label": self.source.label,
            "captured": len(self.items),
            "complete": self.complete,
            "has_more": bool(self.cursor),
            "warnings": list(self.warnings),
            "diagnostics": dict(self.diagnostics),
        }


@dataclass
class SourceInspection:
    source: SourceSpec
    reachable: bool
    title: str = ""
    content_type: str = ""
    capabilities: list[str] = field(default_factory=list)
    item_candidates: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class CapturePlan:
    source_id: str
    adapter: str
    strategy: str
    confidence: float
    required_user_actions: list[str] = field(default_factory=list)
    validation_checks: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class SourceAdapter(Protocol):
    """Adapter contract. Implementations must not hide incomplete captures."""
    name: str
    kinds: tuple[SourceKind, ...]

    def inspect(self, source: SourceSpec, **context: Any) -> SourceInspection: ...

    def sample(self, source: SourceSpec, limit: int = 10, **context: Any) -> CaptureBatch: ...

    def capture(self, source: SourceSpec, limit: int = 1000, cursor: str | None = None,
                **context: Any) -> CaptureBatch: ...
