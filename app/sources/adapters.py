"""Initial generic adapters: pasted text and structured local files.

Browser acquisition is intentionally a separate adapter because it needs a live,
user-authenticated Playwright page. It is added in browser_adapter.py and shares
the same contracts; no adapter owns extraction schema or business semantics.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from .contracts import CaptureBatch, SourceInspection, SourceItem, SourceKind, SourceSpec


class TextSourceAdapter:
    name = "text"
    kinds = (SourceKind.TEXT,)

    def inspect(self, source: SourceSpec, **context: Any) -> SourceInspection:
        text = str(context.get("text") or source.options.get("text") or "")
        return SourceInspection(source, bool(text.strip()), title=source.label,
                                content_type="text/plain", capabilities=["sample", "capture"],
                                evidence={"characters": len(text)})

    def sample(self, source: SourceSpec, limit: int = 10, **context: Any) -> CaptureBatch:
        return self.capture(source, limit=limit, **context)

    def capture(self, source: SourceSpec, limit: int = 1000, cursor: str | None = None,
                **context: Any) -> CaptureBatch:
        text = str(context.get("text") or source.options.get("text") or "")
        chunks = [part.strip() for part in text.replace("\r\n", "\n").split("\n\n") if part.strip()]
        start = int(cursor or 0)
        end = min(len(chunks), start + max(1, limit))
        items = [SourceItem(content=chunk, source_id=source.id, source_label=source.label,
                            source_uri=source.uri, item_id=f"text:{i+1}", item_type="text")
                 for i, chunk in enumerate(chunks[start:end], start)]
        return CaptureBatch(source, items, complete=end >= len(chunks),
                            cursor=None if end >= len(chunks) else str(end),
                            diagnostics={"segments_found": len(chunks), "segmentation": "blank_lines"}).validate()


class FileSourceAdapter:
    name = "file"
    kinds = (SourceKind.FILE,)
    SUPPORTED = {".txt", ".csv", ".json", ".jsonl"}

    def _rows(self, filename: str, content: bytes | str) -> list[dict[str, Any]]:
        raw = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else str(content)
        suffix = Path(filename).suffix.lower()
        if suffix == ".txt":
            return [{"content": row.strip(), "item_type": "text"} for row in raw.split("\n\n") if row.strip()]
        if suffix == ".jsonl":
            rows = []
            for line_no, line in enumerate(raw.splitlines(), 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                rows.append({"content": json.dumps(value, ensure_ascii=False), "item_type": "json", "metadata": {"line": line_no}})
            return rows
        if suffix == ".json":
            value = json.loads(raw)
            values = value if isinstance(value, list) else [value]
            return [{"content": json.dumps(row, ensure_ascii=False), "item_type": "json", "metadata": {"row": i}}
                    for i, row in enumerate(values, 1)]
        if suffix == ".csv":
            return [{"content": json.dumps(row, ensure_ascii=False), "item_type": "record", "metadata": {"row": i}}
                    for i, row in enumerate(csv.DictReader(io.StringIO(raw)), 1)]
        raise ValueError(f"Unsupported file type: {suffix}")

    def inspect(self, source: SourceSpec, **context: Any) -> SourceInspection:  # type: ignore[override]
        filename = str(context.get("filename") or source.options.get("filename") or source.label)
        suffix = Path(filename).suffix.lower()
        content = context.get("content")
        ok = suffix in self.SUPPORTED and isinstance(content, (bytes, str))
        evidence = {"extension": suffix, "bytes": len(content) if content is not None else 0}
        if ok:
            try:
                evidence["items_detected"] = len(self._rows(filename, content))
            except Exception as exc:
                return SourceInspection(source, False, title=filename, warnings=[f"Could not parse file: {exc}"], evidence=evidence)
        return SourceInspection(source, ok, title=filename, content_type=source.content_type or suffix,
                                capabilities=["sample", "capture"] if ok else [],
                                warnings=[] if ok else [f"Unsupported or missing file content: {suffix or 'unknown'}"], evidence=evidence)

    def sample(self, source: SourceSpec, limit: int = 10, **context: Any) -> CaptureBatch:
        return self.capture(source, limit=limit, **context)

    def capture(self, source: SourceSpec, limit: int = 1000, cursor: str | None = None,
                **context: Any) -> CaptureBatch:
        filename = str(context.get("filename") or source.options.get("filename") or source.label)
        rows = self._rows(filename, context.get("content", b""))
        start = int(cursor or 0)
        end = min(len(rows), start + max(1, limit))
        items = [SourceItem(content=str(row["content"]), source_id=source.id, source_label=source.label,
                            source_uri=source.uri, item_id=f"{filename}:{i+1}", item_type=row.get("item_type", "record"),
                            content_type=source.content_type or "text/plain", metadata=row.get("metadata", {}))
                 for i, row in enumerate(rows[start:end], start)]
        return CaptureBatch(source, items, complete=end >= len(rows), cursor=None if end >= len(rows) else str(end),
                            diagnostics={"rows_total": len(rows), "rows_read": len(items), "offset": start}).validate()
