from .contracts import (CaptureBatch, CapturePlan, SourceInspection, SourceItem,
                        SourceKind, SourceSpec, SourceAdapter)
from .registry import SourceRegistry
from .adapters import FileSourceAdapter, TextSourceAdapter
from .browser_adapter import BrowserDOMSourceAdapter
from .planner import plan_source


def default_registry() -> SourceRegistry:
    return SourceRegistry((TextSourceAdapter(), FileSourceAdapter(), BrowserDOMSourceAdapter()))


__all__ = ["CaptureBatch", "CapturePlan", "SourceInspection", "SourceItem", "SourceKind",
           "SourceSpec", "SourceAdapter", "SourceRegistry", "FileSourceAdapter",
           "TextSourceAdapter", "BrowserDOMSourceAdapter", "plan_source", "default_registry"]
