#!/usr/bin/env python3
"""Standalone, keyboard-first terminal review desk for Agent Shadi.

This is a real terminal UI (curses), not an input field embedded in the web UI.
It shares the local API and database with Agent Shadi.
"""
from __future__ import annotations

import curses
import json
import math
import os
from pathlib import Path

try:
    from wcwidth import wcwidth
except ImportError:  # graceful fallback for minimal terminal environments
    import unicodedata
    def wcwidth(char: str) -> int:
        if unicodedata.combining(char):
            return 0
        return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
from typing import Any

from review_terminal import ReviewTerminal, api, ensure_server, parse_rows, color


def notify_launch_state(state: str, detail: str = "") -> None:
    """Signal the local API only after the real terminal UI is initialized."""
    target = os.environ.get("AGENT_SHADI_REVIEW_HANDSHAKE", "").strip()
    if not target:
        return
    path = Path(target)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps({"state": state, "detail": detail[:1200], "pid": os.getpid()}), encoding="utf-8")
        temp.replace(path)
    except Exception:
        pass


class ReviewDesk:
    def __init__(self, screen: Any) -> None:
        self.screen = screen
        self.session = ReviewTerminal()
        self.session.limit = 50
        self.index = 0
        self.selected: set[str] = set()
        self.awaiting_advance = False
        self.live_record: dict[str, Any] | None = None
        self.issue = "all"
        self.detail_scroll = 0
        self.extract_scroll = 0
        self.pane_tab = "extraction" if self.path == "processed" else "message"
        self.status = "↑/↓ move   A approve   R reject   E edit   X extract (Live AI)   : commands   ? help   Q quit"
        self.error = False
        self.batch = False
        self.confirm_bulk = True
        self.running = True
        self._init_screen()
        self._launch_ready_reported = False
        ensure_server()
        self.session.load_workflows()
        self._load_settings()
        self.pane_tab = "extraction" if self.path == "processed" else "message"
        self.refresh(preserve=True)
        self.auto_extract_pending = self.path == "live" and bool(self.session.items)

    def _init_screen(self) -> None:
        self.screen.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        try:
            curses.start_color()
            curses.use_default_colors()
            pairs = [
                (1, curses.COLOR_WHITE, -1),
                (2, curses.COLOR_MAGENTA, -1),
                (3, curses.COLOR_CYAN, -1),
                (4, curses.COLOR_GREEN, -1),
                (5, curses.COLOR_YELLOW, -1),
                (6, curses.COLOR_RED, -1),
                (7, curses.COLOR_BLACK, curses.COLOR_CYAN),
                (8, curses.COLOR_BLACK, curses.COLOR_MAGENTA),
                (9, curses.COLOR_BLUE, -1),
            ]
            for pair, fg, bg in pairs:
                curses.init_pair(pair, fg, bg)
        except curses.error:
            pass
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        except curses.error:
            pass

    def _load_settings(self) -> None:
        self.session.load_workflow_settings()
        settings = self.session.review_settings
        self.session.path = settings.get("processing_path", "processed")
        self.session.limit = int(settings.get("page_size", 50) or 50)
        self.session.review_settings.setdefault("mode", "guided")
        self.batch = self.session.review_settings.get("mode") == "batch"
        self.confirm_bulk = self.session.review_settings.get("confirm_bulk", True) is not False
        self.issue = "all"

    @property
    def path(self) -> str:
        return self.session.path

    @property
    def workflow_name(self) -> str:
        return str((self.session.workflow or {}).get("name", "No workflow"))

    def save_settings(self, **patch: Any) -> None:
        current = dict(self.session.review_settings)
        body = {
            "enabled": self.session.review_enabled,
            "mode": patch.get("mode", current.get("mode", "guided")),
            "processing_path": patch.get("processing_path", self.path),
            "auto_advance": patch.get("auto_advance", current.get("auto_advance", True)),
            "confirm_bulk": patch.get("confirm_bulk", current.get("confirm_bulk", True)),
            "page_size": patch.get("page_size", current.get("page_size", self.session.limit)),
            "sort": patch.get("sort", current.get("sort", "newest")),
        }
        result = api("PUT", f"/api/workflows/{self.session.wid}/review/settings", body)
        self.session.review_settings = result.get("review_settings", body)
        self.session.review_enabled = result.get("review_mode", self.session.review_enabled)
        self.session.path = self.session.review_settings.get("processing_path", self.path)
        self.session.limit = int(self.session.review_settings.get("page_size", self.session.limit))
        self.batch = self.session.review_settings.get("mode") == "batch"
        self.confirm_bulk = self.session.review_settings.get("confirm_bulk", True) is not False

    def refresh(self, preserve: bool = True) -> None:
        old_id = self.current_id() if preserve else None
        params = {"limit": self.session.limit, "offset": self.session.offset,
                  "q": self.session.query, "source": self.session.source}
        if self.path == "live":
            data = api("GET", f"/api/workflows/{self.session.wid}/review/live/queue?{self._query(params)}")
        else:
            params.update({"issue": self.issue, "sort": self.session.review_settings.get("sort", "newest")})
            data = api("GET", f"/api/workflows/{self.session.wid}/review/queue?{self._query(params)}")
        self.session.items = data.get("items", [])
        self.session.total = int(data.get("total", 0))
        self.session.has_more = bool(data.get("has_more", False))
        self.session.review_settings.update(data.get("settings", {}))
        if old_id:
            idx = next((i for i, item in enumerate(self.session.items) if item.get("id") == old_id), None)
            if idx is not None:
                self.index = idx
        self.index = max(0, min(self.index, max(0, len(self.session.items) - 1)))
        visible = {str(item.get("id")) for item in self.session.items}
        self.selected.intersection_update(visible)

    @staticmethod
    def _query(params: dict[str, Any]) -> str:
        from urllib.parse import urlencode
        return urlencode(params)

    def current_id(self) -> str | None:
        if self.live_record:
            return str(self.live_record.get("id"))
        if 0 <= self.index < len(self.session.items):
            return str(self.session.items[self.index].get("id"))
        return None

    def current_item(self) -> dict[str, Any] | None:
        if self.live_record:
            return self.live_record
        if 0 <= self.index < len(self.session.items):
            return self.session.items[self.index]
        return None

    @staticmethod
    def _clip_cells(value: str, width: int) -> str:
        """Clip by terminal display cells, not Python code points.

        This is important for Persian/Arabic combining marks, CJK characters and
        emoji: addnstr's character count is not a reliable pane-width boundary.
        """
        if width <= 0:
            return ""
        out: list[str] = []
        used = 0
        for char in value:
            cell_width = wcwidth(char)
            if cell_width < 0:
                continue
            if used + cell_width > width:
                break
            out.append(char)
            used += cell_width
        return "".join(out)

    def _put(self, y: int, x: int, value: Any, attr: int = 0, width: int | None = None) -> None:
        rows, cols = self.screen.getmaxyx()
        if y < 0 or y >= rows or x < 0 or x >= cols:
            return
        text = str(value).replace("\n", " ").replace("\r", " ").replace("\t", " ")
        available = max(0, cols - x - 1) if width is None else max(0, min(width, cols - x - 1))
        if available <= 0:
            return
        text = self._clip_cells(text, available)
        if not text:
            return
        try:
            # The text is already bounded by terminal cell width. Passing its
            # code-point length avoids curses re-applying a narrower cell count.
            self.screen.addnstr(y, x, text, len(text), attr)
        except (curses.error, UnicodeError):
            try:
                safe = text.encode("ascii", "replace").decode("ascii")
                self.screen.addnstr(y, x, safe, len(safe), attr)
            except curses.error:
                pass

    def _hline(self, y: int, x: int, width: int, char: str = "─", attr: int = 0) -> None:
        self._put(y, x, char * max(0, width), attr, width)

    def _vline(self, y: int, end_y: int, x: int, char: str = "│", attr: int = 0) -> None:
        for row in range(max(0, y), min(end_y, self.screen.getmaxyx()[0])):
            self._put(row, x, char, attr, 1)

    @staticmethod
    def _display_width(value: str) -> int:
        return sum(max(0, wcwidth(char)) for char in value)

    @staticmethod
    def _wrap(value: Any, width: int) -> list[str]:
        """Wrap logical text using terminal-cell widths; never emit overflow."""
        raw = str(value or "")
        width = max(1, int(width))
        result: list[str] = []
        for paragraph in raw.splitlines() or [""]:
            if not paragraph:
                result.append("")
                continue
            words = paragraph.split()
            line = ""
            for word in words:
                candidate = f"{line} {word}" if line else word
                if ReviewDesk._display_width(candidate) <= width:
                    line = candidate
                    continue
                if line:
                    result.append(line)
                    line = ""
                chunk = ""
                for char in word:
                    if chunk and ReviewDesk._display_width(chunk + char) > width:
                        result.append(chunk)
                        chunk = char
                    else:
                        chunk += char
                line = chunk
            if line:
                result.append(line)
        return result or [""]

    def draw(self) -> None:
        self.screen.erase()
        rows, cols = self.screen.getmaxyx()
        if rows < 18 or cols < 96:
            self._put(0, 0, "Agent Shadi Review Desk needs a terminal at least 96x18 for the three-panel inspector.", curses.A_BOLD)
            self._put(2, 0, f"Current size: {cols}x{rows}. Maximize the terminal or widen it, then press any key.")
            self.screen.refresh()
            return
        purple = curses.color_pair(2) | curses.A_BOLD
        cyan = curses.color_pair(3) | curses.A_BOLD
        dim = curses.A_DIM
        green = curses.color_pair(4) | curses.A_BOLD
        yellow = curses.color_pair(5) | curses.A_BOLD
        red = curses.color_pair(6) | curses.A_BOLD
        line = curses.color_pair(9)
        mode = "LIVE AI · ONE RAW MESSAGE PER LLM CALL" if self.path == "live" else "EXTRACTED RESULTS · ONE-BY-ONE APPROVAL"
        self._put(0, 1, "AGENT SHADI  /  REVIEW DESK", purple)
        self._put(0, max(2, cols - len(mode) - 3), mode, cyan)
        self._put(1, 1, f"WORKFLOW  {self.workflow_name}     QUEUE  {len(self.session.items)} visible / {self.session.total} waiting     PAGE OFFSET  {self.session.offset}", dim)
        self._hline(2, 1, cols - 3, "─", line)

        # Three persistent panes: queue, complete original source, and extraction.
        # The source and extracted values remain visible together while either can
        # be scrolled independently with Tab selecting the active scroll target.
        left_w = max(28, min(36, int(cols * 0.30)))
        message_x = left_w + 2
        available = cols - message_x - 3
        message_w = max(30, int(available * 0.56))
        extract_x = message_x + message_w + 1
        extract_w = cols - extract_x - 2
        self._put(3, 1, "NUMBERED QUEUE", cyan)
        self._put(3, message_x, "[ ORIGINAL MESSAGE ]" if self.pane_tab == "message" else "ORIGINAL MESSAGE", cyan)
        self._put(3, extract_x, "[ EXTRACTED VALUES ]" if self.pane_tab == "extraction" else "EXTRACTED VALUES", cyan)
        self._hline(4, 1, left_w, "─", line)
        self._hline(4, message_x, message_w, "─", line)
        self._hline(4, extract_x, extract_w, "─", line)
        list_top, list_bottom = 5, rows - 5
        item_height = 2
        list_capacity = max(1, (list_bottom - list_top) // item_height)
        start = max(0, min(self.index - list_capacity + 1, max(0, len(self.session.items) - list_capacity)))
        for screen_row in range(list_capacity):
            idx = start + screen_row
            if idx >= len(self.session.items):
                break
            item_row = self.session.items[idx]
            number = idx + 1
            selected = idx == self.index and not self.awaiting_advance
            chosen = "✓" if item_row.get("id") in self.selected else " "
            if self.path == "live":
                state = str(item_row.get("status", "queued")).upper()
            else:
                state = "ERR" if item_row.get("errors") else "WARN" if item_row.get("warnings") else "OK"
            row_attr = (curses.color_pair(7) | curses.A_BOLD) if selected else (dim if idx % 2 else 0)
            self._put(list_top + screen_row * item_height, 1, f"{number:>3} {chosen} {state:<4}", row_attr)
            self._put(list_top + screen_row * item_height, 14, str(item_row.get("source") or "Unknown"), row_attr, max(8, left_w - 16))
            if self.path == "live":
                preview = str(item_row.get("raw_text", "")).replace("\n", " ")
            else:
                preview = " · ".join(str(v) for v in (item_row.get("data") or {}).values() if v not in (None, ""))
            self._put(list_top + screen_row * item_height + 1, 14,
                      self._wrap(preview, max(8, left_w - 16))[0] if preview else "(empty preview)", dim, max(8, left_w - 16))
            self._put(list_top + screen_row * item_height, left_w, "│", dim)
            self._put(list_top + screen_row * item_height + 1, left_w, "│", dim)

        item = self.current_item()
        content_top = 8
        content_height = max(1, rows - content_top - 5)
        if self.awaiting_advance:
            self._put(5, message_x, "DECISION SAVED", green, message_w)
            self._put(6, message_x, "Auto-advance is OFF. Press Enter or N for the next item.", dim, message_w)
            self._put(5, extract_x, "WAITING FOR OPERATOR", yellow, extract_w)
        elif item is None:
            self._put(5, message_x, "Queue is clear.", green, message_w)
            self._put(5, extract_x, "No extraction selected.", dim, extract_w)
        else:
            self._put(5, message_x, f"SOURCE  {item.get('source') or 'Unknown source'}", yellow, message_w)
            self._put(6, message_x, f"DATE    {item.get('posted_at') or 'Unavailable'}", dim, message_w)
            raw = item.get("raw_text", "Original message unavailable")
            message_lines = self._wrap(raw, message_w - 2)
            self.detail_scroll = min(self.detail_scroll, max(0, len(message_lines) - content_height))
            for offset, ln in enumerate(message_lines[self.detail_scroll:self.detail_scroll + content_height]):
                self._put(content_top + offset, message_x, ln, 0, message_w - 1)
            if len(message_lines) > content_height:
                self._put(rows - 5, message_x,
                          f"Message {self.detail_scroll + 1}–{min(self.detail_scroll + content_height, len(message_lines))}/{len(message_lines)}",
                          dim, message_w)
            if item.get("error"):
                self._put(rows - 6, message_x, "PREVIOUS ERROR: " + str(item.get("error")), red, message_w)

            data = item.get("data", {}) or {}
            schema_fields = ((((getattr(self.session, "workflow", None) or {}).get("config") or {}).get("fields")) or [])
            labels = {str(field.get("name")): str(field.get("label") or field.get("name"))
                      for field in schema_fields if isinstance(field, dict)}
            palette = [3, 4, 5, 2, 9]
            extraction_lines: list[tuple[str, int]] = []
            if not (self.path == "processed" or self.live_record):
                extraction_lines.append(("No extraction yet. Switch to Live AI and extract this message first.", dim))
            else:
                ordered_keys = [str(field.get("name")) for field in schema_fields if isinstance(field, dict) and str(field.get("name")) in data]
                ordered_keys.extend(str(key) for key in data if str(key) not in ordered_keys)
                if not ordered_keys:
                    extraction_lines.append(("No extracted values.", yellow))
                for field_index, key in enumerate(ordered_keys):
                    value = data.get(key)
                    label = labels.get(key) or key.replace("_", " ").strip().title()
                    if value is None or value == "":
                        value_text = "—"
                    elif isinstance(value, (dict, list)):
                        value_text = json.dumps(value, ensure_ascii=False, separators=(",", ": "))
                    else:
                        value_text = str(value)
                    field_attr = curses.color_pair(palette[field_index % len(palette)]) | curses.A_BOLD
                    value_attr = curses.color_pair(palette[field_index % len(palette)])
                    extraction_lines.append((label, field_attr))
                    value_lines = self._wrap(value_text, max(8, extract_w - 5))
                    extraction_lines.extend((f"  {line}", value_attr) for line in value_lines)
                    extraction_lines.append(("", dim))
            self.extract_scroll = min(self.extract_scroll, max(0, len(extraction_lines) - content_height))
            for offset, (ln, attr) in enumerate(extraction_lines[self.extract_scroll:self.extract_scroll + content_height]):
                self._put(content_top + offset, extract_x, ln, attr, extract_w - 1)
            if len(extraction_lines) > content_height:
                self._put(rows - 5, extract_x,
                          f"Fields {self.extract_scroll + 1}–{min(self.extract_scroll + content_height, len(extraction_lines))}/{len(extraction_lines)}",
                          dim, extract_w)

        # Draw pane separators last. Text is clipped to cell widths above, and
        # these hard borders make the message/extraction boundary explicit even
        # with RTL scripts or long unbroken English/URL tokens.
        self._vline(3, rows - 4, left_w, "│", line)
        self._vline(3, rows - 4, extract_x - 1, "│", line)
        self._hline(rows - 4, 1, cols - 3, "─", line)
        auto = "AUTO-NEXT" if self.session.review_settings.get("auto_advance", True) else "PAUSE AFTER DECISION"
        mode_label = "BATCH" if self.batch else "GUIDED"
        self._put(rows - 3, 1, f"{mode_label}  ·  {auto}  ·  SELECTED {len(self.selected)}", purple)
        status_attr = red if self.error else yellow
        self._put(rows - 2, 1, self.status, status_attr, cols - 3)
        focus = "MESSAGE" if self.pane_tab == "message" else "EXTRACTION"
        self._put(rows - 1, 1, f"↑/↓ move  Tab focus:{focus}  PgUp/PgDn scroll focused pane  A approve  R reject  E edit  X extract  F2 path  F3 workflow  ? help  Q quit", dim, cols - 3)
        self.screen.refresh()

    def message(self, text: str, error: bool = False) -> None:
        self.status = text
        self.error = error

    def prompt(self, label: str) -> str:
        rows, cols = self.screen.getmaxyx()
        try: curses.curs_set(1)
        except curses.error: pass
        value = ""
        while True:
            self._put(rows - 2, 1, " " * (cols - 3), curses.A_REVERSE, cols - 3)
            self._put(rows - 2, 1, f"{label}: {value}", curses.A_REVERSE, cols - 3)
            self.screen.refresh()
            ch = self.screen.get_wch()
            if ch in ("\n", "\r", curses.KEY_ENTER):
                break
            if ch in ("\x1b",):
                value = ""; break
            if ch in ("\b", "\x7f", curses.KEY_BACKSPACE):
                value = value[:-1]
            elif isinstance(ch, str) and ch.isprintable() and len(value) < 500:
                value += ch
        try: curses.curs_set(0)
        except curses.error: pass
        return value.strip()

    def confirm(self, prompt: str) -> bool:
        rows, cols = self.screen.getmaxyx()
        question = f"{prompt}  [y/N]"
        self._put(rows - 2, max(1, (cols - len(question)) // 2), question, curses.color_pair(5) | curses.A_BOLD)
        self.screen.refresh()
        ch = self.screen.get_wch()
        return isinstance(ch, str) and ch.lower() == "y"

    def help(self) -> None:
        self.screen.erase()
        rows, cols = self.screen.getmaxyx()
        entries = [
            "AGENT SHADI — REVIEW DESK / KEYBOARD MAP",
            "",
            "NAVIGATION",
            "  Up / Down or J / K    Move between messages/records",
            "  Enter or N            Continue after manual pause / move next",
            "  P                     Previous record",
            "  Home / End            First / last visible item",
            "  Tab                   Switch right inspector: Message / Extraction",
            "  PageUp / PageDown     Scroll the current inspector tab",
            "  : page next / prev    Move between queue pages",
            "  1–9                   Jump directly to a visible row",
            "",
            "DECISIONS",
            "  A                     Approve only the focused extracted result",
            "  R                     Reject only the focused result (confirmation)",
            "  E                     Edit fields in your $EDITOR, then validate/save",
            "  X                     Live AI mode: send exactly the focused raw message to LLM",
            "  [ / ]                 Scroll the current inspector tab by five lines",
            "  Space                 Select/deselect focused row (Batch mode)",
            "  B                     Toggle Guided / Batch review",
            "  U                     Undo last decision",
            "",
            "WORKSPACE",
            "  F2                    Switch Review extracted / Live AI paths",
            "  F3                    Switch workflow",
            "  F5 or Ctrl+R          Refresh queue",
            "  /                     Search source/message/fields",
            "  F                     Change quality filter (errors/warnings/low confidence)",
            "  :                     Open command bar; supports ranges e.g. approve 1-5",
            "  Q                     Quit (no data is deleted)",
            "",
            "EXAMPLES IN COMMAND BAR",
            "  approve 1-5     reject 2,4     select 3-8     search apartment",
            "  path live       path processed     workflow 2     undo     help",
            "",
            "Press any key to return.",
        ]
        for y, line in enumerate(entries[:rows - 1]):
            self._put(y, 2, line, curses.color_pair(2) | curses.A_BOLD if y in (0, 2, 10, 20) else 0)
        self.screen.refresh(); self.screen.get_wch()

    def _edit_record(self, record: dict[str, Any]) -> None:
        """Edit schema values in-place; number keys jump directly to a field."""
        data = dict(record.get("data") or {})
        schema = ((((getattr(self.session, "workflow", None) or {}).get("config") or {}).get("fields")) or [])
        fields = [f for f in schema if isinstance(f, dict) and str(f.get("name") or "") in data]
        known = {str(f.get("name")) for f in fields}
        fields.extend({"name": key, "label": str(key).replace("_", " ").title(), "type": "string"}
                      for key in data if str(key) not in known)
        if not fields:
            self.message("This record has no editable output fields.", True)
            return
        selected = 0
        saved = False
        rows, cols = self.screen.getmaxyx()
        while True:
            self.screen.erase()
            self._put(0, 1, "EDIT EXTRACTED VALUES", curses.color_pair(2) | curses.A_BOLD)
            self._put(1, 1, "Select a variable by number or ↑/↓. Press Enter/E to replace its value.", curses.A_DIM)
            self._hline(2, 1, cols - 3, "─", curses.color_pair(9))
            visible = max(1, rows - 10)
            start = max(0, min(selected - visible + 1, len(fields) - visible))
            for offset, field in enumerate(fields[start:start + visible]):
                idx = start + offset
                name = str(field.get("name") or "")
                label = str(field.get("label") or name)
                value = data.get(name)
                if isinstance(value, (dict, list)):
                    rendered = json.dumps(value, ensure_ascii=False, separators=(",", ": "))
                else:
                    rendered = "—" if value is None or value == "" else str(value)
                attr = curses.color_pair(7) | curses.A_BOLD if idx == selected else curses.A_NORMAL
                self._put(4 + offset, 2, f"{idx + 1:>3}. {label}  [{field.get('type') or 'string'}]", attr, cols - 5)
                self._put(5 + offset, 7, rendered, curses.A_DIM if idx != selected else curses.color_pair(3), cols - 10)
            self._hline(rows - 4, 1, cols - 3, "─", curses.color_pair(9))
            self._put(rows - 3, 1, "Enter/E edit · ↑/↓ or J/K move · 1–9 jump · S save · Esc/Q cancel", curses.A_DIM, cols - 3)
            self.screen.refresh()
            key = self.screen.get_wch()
            if key in ("\x1b", "q", "Q"):
                self.message("Edit cancelled; no changes were saved.")
                break
            if key in (curses.KEY_UP, "k", "K"):
                selected = max(0, selected - 1)
                continue
            if key in (curses.KEY_DOWN, "j", "J"):
                selected = min(len(fields) - 1, selected + 1)
                continue
            if isinstance(key, str) and key.isdigit() and key != "0":
                target = int(key) - 1
                if target < len(fields):
                    selected = target
                    field = fields[selected]
                    name = str(field.get("name") or "")
                    current = data.get(name)
                    current_text = json.dumps(current, ensure_ascii=False) if isinstance(current, (dict, list)) else ("" if current is None else str(current))
                    label = str(field.get("label") or name)
                    replacement = self._prompt_edit_value(label, current_text)
                    if replacement is not None:
                        try:
                            data[name] = self._coerce_review_value(replacement, str(field.get("type") or "string"))
                        except ValueError as exc:
                            self.message(f"{label}: {exc}", True)
                continue
            if key in ("s", "S"):
                try:
                    result = api("PUT", f"/api/records/{record['id']}", {"data": data})
                    # Update the focused in-memory row immediately, then reload
                    # the queue while preserving its record ID and selection.
                    record["data"] = dict(result.get("data") or data)
                    record["errors"] = list(result.get("errors") or [])
                    for item in self.session.items:
                        if str(item.get("id")) == str(record.get("id")):
                            item["data"] = dict(record["data"])
                            item["errors"] = list(record["errors"])
                            break
                    self.message(f"Saved correction and refreshed live record. {len(result.get('changed', {}))} field(s) changed.")
                    saved = True
                except Exception as exc:
                    self.message(f"Could not save correction: {exc}", True)
                break
            if key in ("e", "E", "\n", "\r", curses.KEY_ENTER):
                field = fields[selected]
                name = str(field.get("name") or "")
                current = data.get(name)
                if isinstance(current, (dict, list)):
                    current_text = json.dumps(current, ensure_ascii=False)
                else:
                    current_text = "" if current is None else str(current)
                label = str(field.get("label") or name)
                replacement = self._prompt_edit_value(label, current_text)
                if replacement is None:
                    continue
                try:
                    data[name] = self._coerce_review_value(replacement, str(field.get("type") or "string"))
                except ValueError as exc:
                    self.message(f"{label}: {exc}", True)
                    continue
        if saved:
            self.refresh(preserve=True)
            self.draw()
        else:
            self.draw()

    def _prompt_edit_value(self, label: str, current: str) -> str | None:
        """A replacement prompt: typing starts a fresh value; Esc keeps the old one."""
        rows, cols = self.screen.getmaxyx()
        try: curses.curs_set(1)
        except curses.error: pass
        value = ""
        while True:
            self._put(rows - 3, 1, " " * (cols - 3), curses.A_REVERSE, cols - 3)
            self._put(rows - 3, 1, f"{label} · current: {current[:max(10, cols - 45)]}", curses.A_REVERSE, cols - 3)
            self._put(rows - 2, 1, " " * (cols - 3), curses.A_REVERSE, cols - 3)
            self._put(rows - 2, 1, f"New value (blank = null): {value}", curses.A_REVERSE, cols - 3)
            self.screen.refresh()
            ch = self.screen.get_wch()
            if ch in ("\n", "\r", curses.KEY_ENTER):
                break
            if ch == "\x1b":
                value = None
                break
            if ch in ("\b", "\x7f", curses.KEY_BACKSPACE):
                value = value[:-1]
            elif ch == "\x15":  # Ctrl+U clears the replacement field.
                value = ""
            elif isinstance(ch, str) and ch.isprintable() and len(value) < 4000:
                value += ch
        try: curses.curs_set(0)
        except curses.error: pass
        return value

    @staticmethod
    def _coerce_review_value(value: str, field_type: str) -> Any:
        value = str(value)
        if not value.strip():
            return None
        if field_type == "integer":
            number = float(value.strip())
            if not number.is_integer(): raise ValueError("enter a whole number")
            return int(number)
        if field_type == "number":
            number = float(value.strip())
            if not math.isfinite(number): raise ValueError("enter a finite number")
            return number
        if field_type == "boolean":
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "1", "بله"}: return True
            if normalized in {"false", "no", "0", "خیر"}: return False
            raise ValueError("enter true/false, yes/no, or بله/خیر")
        if field_type in {"array", "object"}:
            parsed = json.loads(value)
            if field_type == "array" and not isinstance(parsed, list): raise ValueError("enter a JSON array")
            if field_type == "object" and not isinstance(parsed, dict): raise ValueError("enter a JSON object")
            return parsed
        return value

    def _decision(self, action: str, ids: list[str]) -> None:
        ids = list(dict.fromkeys(ids))
        if not ids:
            self.message("No records selected.", True); return
        if action == "reject" and not self.confirm(f"Reject {len(ids)} record(s)?"):
            self.message("Rejection cancelled."); return
        if len(ids) > 1 and self.confirm_bulk and not self.confirm(f"{action.title()} {len(ids)} records in one batch?"):
            self.message("Batch decision cancelled."); return
        if len(ids) == 1:
            result = api("POST", f"/api/records/{ids[0]}/{action}", {"reason": "Standalone Review Desk decision"} if action == "reject" else None)
        else:
            result = api("POST", f"/api/workflows/{self.session.wid}/records/bulk-action", {"ids": ids, "action": action, "reason": f"Standalone Review Desk batch {action}"})
        self.session.undo_token = result.get("undo_token") or self.session.undo_token
        for rid in ids:
            self.selected.discard(rid)
        self.live_record = None
        old_index = self.index
        self.refresh(preserve=False)
        self.index = min(old_index, max(0, len(self.session.items) - 1))
        if not self.batch and not self.session.review_settings.get("auto_advance", True):
            self.awaiting_advance = True
        else:
            self.awaiting_advance = False
        self.message(f"{result.get('updated', len(ids))} record(s) {action}d. Undo is available with U.")
        if self.path == "live" and not self.awaiting_advance and self.session.items:
            self.extract()

    def approve(self) -> None:
        item = self.current_item()
        if not item:
            self.message("Nothing is focused.", True); return
        self._decision("approve", [str(item["id"])])

    def reject(self) -> None:
        item = self.current_item()
        if not item:
            self.message("Nothing is focused.", True); return
        self._decision("reject", [str(item["id"])])

    def extract(self) -> None:
        if self.path != "live":
            self.message("Switch to Live AI with F2 before extracting a raw message.", True); return
        if self.live_record:
            self.message("Decide on the current AI result before extracting another message.", True); return
        item = self.current_item()
        if not item:
            self.message("No raw message is focused.", True); return
        self.message("Sending exactly one selected message to the configured LLM…")
        self.draw()
        data = api("POST", f"/api/workflows/{self.session.wid}/review/live/{item['id']}/extract")
        self.live_record = data.get("record")
        self.pane_tab = "extraction"
        self.extract_scroll = 0
        self.refresh(preserve=False)
        self.message("Extraction complete. Review the result, then A approve / R reject / E edit.")

    def undo(self) -> None:
        if not self.session.undo_token:
            self.message("No undoable decision in this session.", True); return
        result = api("POST", f"/api/workflows/{self.session.wid}/quality/undo", {"undo_token": self.session.undo_token})
        self.session.undo_token = None; self.live_record = None; self.awaiting_advance = False
        self.refresh(preserve=False)
        self.message(f"Undo restored {result.get('restored', 0)} action(s).")

    def change_path(self) -> None:
        if self.live_record:
            self.message("Approve/reject the current live result before changing paths.", True); return
        new_path = "live" if self.path == "processed" else "processed"
        self.save_settings(processing_path=new_path, mode="guided")
        self.session.offset = 0; self.index = 0; self.selected.clear(); self.live_record = None
        self.pane_tab = "message" if new_path == "live" else "extraction"
        self.detail_scroll = 0; self.extract_scroll = 0
        self.batch = False; self.awaiting_advance = False; self.refresh(preserve=False)
        label = "Live AI · one raw message per LLM call" if new_path == "live" else "Review extracted results · one by one"
        self.message(f"Review path changed to {label}.")
        if new_path == "live" and self.session.items:
            self.extract()

    def change_workflow(self) -> None:
        self.screen.erase(); self._put(0, 2, "WORKFLOWS — enter a number, Esc to cancel", curses.A_BOLD)
        for i, workflow in enumerate(self.session.workflows[:min(20, self.screen.getmaxyx()[0] - 3)], 1):
            self._put(i + 1, 3, f"{i:>2}. {workflow.get('name', 'Workflow')}")
        self.screen.refresh()
        choice = self.prompt("Workflow number")
        if not choice:
            self.draw(); return
        if not choice.isdigit() or not 1 <= int(choice) <= len(self.session.workflows):
            self.message("Invalid workflow number.", True); return
        self.session.workflow = self.session.workflows[int(choice) - 1]
        self.session.offset = 0; self.index = 0; self.selected.clear(); self.live_record = None
        self.pane_tab = "extraction" if self.path == "processed" else "message"
        self.detail_scroll = 0; self.extract_scroll = 0
        self._load_settings(); self.refresh(preserve=False)
        self.message(f"Workflow changed to {self.workflow_name}.")

    def _command(self, value: str) -> None:
        parts = value.strip().split(maxsplit=1)
        if not parts: return
        op = parts[0].lower(); arg = parts[1].strip() if len(parts) > 1 else ""
        if op in {"help", "?"}: self.help(); return
        if op in {"q", "quit", "exit"}: self.running = False; return
        if op == "path":
            if arg not in {"live", "processed"}: raise ValueError("Use path live or path processed")
            if self.live_record: raise ValueError("Decide on the current live result first")
            self.save_settings(processing_path=arg, mode="guided"); self.session.offset=0; self.index=0; self.batch=False; self.refresh(preserve=False); return
        if op == "mode":
            if arg not in {"guided", "batch"}: raise ValueError("Use mode guided or mode batch")
            self.save_settings(mode=arg); self.batch=arg=="batch"; return
        if op in {"approve", "reject"} and arg.lower() == "current":
            item = self.current_item()
            if not item: raise ValueError("No focused result.")
            if self.path == "live" and not self.live_record: raise ValueError("Extract the focused raw message first.")
            self._decision("approve" if op == "approve" else "reject", [str(item["id"])])
            return
        if op in {"a", "approve", "r", "reject", "select", "deselect"}:
            rows = parse_rows(arg.replace("selected", "") if arg not in {"all", "selected"} else "1-"+str(len(self.session.items)), len(self.session.items)) if arg not in {"selected", "all"} else list(range(1, len(self.session.items)+1))
            ids = [str(self.session.items[n-1]["id"]) for n in rows]
            if op in {"select", "deselect"}:
                for rid in ids:
                    if op == "select": self.selected.add(rid)
                    else: self.selected.discard(rid)
                self.message(f"{len(ids)} record(s) {op}ed."); return
            if arg == "selected": ids = list(self.selected)
            if self.path == "live": raise ValueError("Live AI is strictly one-at-a-time; extract, then approve/reject current result.")
            self._decision("approve" if op in {"a", "approve"} else "reject", ids); return
        if op == "extract":
            if arg and arg.lower() != "current":
                self.index = parse_rows(arg, len(self.session.items))[0] - 1
            self.extract(); return
        if op == "search":
            self.session.query=arg; self.session.offset=0; self.index=0; self.refresh(preserve=False); self.message(f"Search: {arg or '(cleared)'}"); return
        if op == "issue":
            if self.path == "live": raise ValueError("Quality issue filters apply to extracted records only")
            if arg not in {"all", "errors", "warnings", "low_confidence", "missing_required"}: raise ValueError("Unknown issue filter")
            self.issue=arg; self.session.offset=0; self.index=0; self.refresh(preserve=False); self.message(f"Issue filter: {arg}"); return
        if op == "workflow":
            if not arg.isdigit() or not 1<=int(arg)<=len(self.session.workflows): raise ValueError("Invalid workflow number")
            self.session.workflow=self.session.workflows[int(arg)-1]; self.session.offset=0; self._load_settings(); self.refresh(preserve=False); return
        if op == "page":
            if arg == "next": self.session.offset += self.session.limit
            elif arg in {"prev", "previous"}: self.session.offset=max(0,self.session.offset-self.session.limit)
            elif arg.isdigit(): self.session.offset=max(0,(int(arg)-1)*self.session.limit)
            else: raise ValueError("Use page next, page prev or page N")
            self.index=0; self.refresh(preserve=False); return
        if op in {"next", "n", "prev", "p"}:
            self.move(1 if op in {"next", "n"} else -1); return
        if op == "undo": self.undo(); return
        if op == "clear":
            self.session.query=""; self.session.source="all"; self.issue="all"; self.session.offset=0; self.selected.clear(); self.refresh(preserve=False); return
        raise ValueError("Unknown command. Press ? for commands.")

    def move(self, delta: int) -> None:
        if self.awaiting_advance:
            self.awaiting_advance = False
            self.message("Continuing guided review.")
            if self.path == "live" and self.session.items:
                self.extract()
            return
        if self.live_record:
            self.message("Decide on this live extraction before moving to another message.", True); return
        target = self.index + delta
        if target >= len(self.session.items) and self.session.has_more:
            self.session.offset += self.session.limit; self.index = 0; self.refresh(preserve=False); return
        if target < 0 and self.session.offset > 0:
            self.session.offset = max(0, self.session.offset-self.session.limit); self.refresh(preserve=False); self.index=max(0,len(self.session.items)-1); return
        self.index = max(0, min(target, max(0, len(self.session.items)-1)))
        self.detail_scroll = 0
        self.extract_scroll = 0
        self.pane_tab = "extraction" if self.path == "processed" or self.live_record else "message"
        if self.path == "live" and self.session.items:
            self.extract()

    def handle(self, key: Any) -> None:
        # Manual guided mode is a hard pause: do not allow a second record to
        # be approved accidentally until the operator explicitly continues.
        if self.awaiting_advance:
            if key in (curses.KEY_DOWN, curses.KEY_ENTER, "j", "J", "\n", "\r", "n", "N"):
                self.move(1)
                return
            if key in ("q", "Q"):
                self.running = False
                return
            if key in ("u", "U"):
                self.undo()
                return
            if key == "?":
                self.help()
                return
            self.message("Guided review is paused. Press Enter or Down to continue to the next record.", True)
            return
        if key in (curses.KEY_UP, "k", "K"): self.move(-1)
        elif key in (curses.KEY_DOWN, "j", "J"): self.move(1)
        elif key in (curses.KEY_ENTER, "\n", "\r", "n", "N"): self.move(1)
        elif key in ("p", "P"): self.move(-1)
        elif key == curses.KEY_HOME: self.index=0; self.detail_scroll=0
        elif key == curses.KEY_END: self.index=max(0,len(self.session.items)-1); self.detail_scroll=0
        elif key in ("\t", curses.KEY_BTAB):
            self.pane_tab = "extraction" if self.pane_tab == "message" else "message"
            self.message("Inspector: " + ("Extraction fields" if self.pane_tab == "extraction" else "Original message"))
        elif key == curses.KEY_NPAGE:
            step = max(3, self.screen.getmaxyx()[0] - 13)
            if self.pane_tab == "message": self.detail_scroll += step
            else: self.extract_scroll += step
        elif key == curses.KEY_PPAGE:
            step = max(3, self.screen.getmaxyx()[0] - 13)
            if self.pane_tab == "message": self.detail_scroll = max(0, self.detail_scroll - step)
            else: self.extract_scroll = max(0, self.extract_scroll - step)
        elif key in ("a", "A"):
            ids = list(self.selected) if self.batch and self.selected else ([self.current_id()] if self.current_id() else [])
            if self.path == "live" and self.live_record: self._decision("approve", [self.live_record["id"]])
            elif self.path == "live": self.message("Live AI requires X (extract) before approval.", True)
            else: self._decision("approve", ids)
        elif key in ("r", "R"):
            ids = list(self.selected) if self.batch and self.selected else ([self.current_id()] if self.current_id() else [])
            if self.path == "live" and self.live_record: self._decision("reject", [self.live_record["id"]])
            elif self.path == "live": self.message("Live AI requires X (extract) before rejection.", True)
            else: self._decision("reject", ids)
        elif key in ("e", "E"):
            item=self.current_item()
            if item and (self.path=="processed" or self.live_record): self._edit_record(item)
            else: self.message("Extract the live message first, then edit the result.", True)
        elif key in ("x", "X"): self.extract()
        elif key in ("u", "U"): self.undo()
        elif key in ("b", "B"):
            self.batch=not self.batch; self.save_settings(mode="batch" if self.batch else "guided")
            self.message("Batch selection enabled." if self.batch else "Guided one-by-one approval enabled.")
        elif key == " ":
            item=self.current_item()
            if self.batch and item and self.path=="processed":
                rid=str(item["id"])
                if rid in self.selected: self.selected.remove(rid)
                else: self.selected.add(rid)
                self.message(f"{len(self.selected)} record(s) selected.")
            else: self.message("Space selects rows only in Batch mode.", True)
        elif key == "f" or key == "F":
            if self.path=="live": self.message("Issue filters apply to extracted results. Use / to search live messages.")
            else:
                choices=["all","errors","warnings","low_confidence","missing_required"]
                self.issue=choices[(choices.index(self.issue)+1)%len(choices)];self.session.offset=0;self.index=0;self.refresh(preserve=False);self.message(f"Issue filter: {self.issue}")
        elif key == curses.KEY_F2: self.change_path()
        elif key == curses.KEY_F3: self.change_workflow()
        elif key == curses.KEY_F5 or key == "\x12": self.refresh(); self.message("Queue refreshed.")
        elif key == "[":
            if self.pane_tab == "message": self.detail_scroll=max(0,self.detail_scroll-5)
            else: self.extract_scroll=max(0,self.extract_scroll-5)
        elif key == "]":
            if self.pane_tab == "message": self.detail_scroll+=5
            else: self.extract_scroll+=5
        elif key == "/":
            value=self.prompt("Search");self.session.query=value;self.session.offset=0;self.index=0;self.refresh(preserve=False);self.message(f"Search: {value or '(cleared)'}")
        elif key == ":":
            command=self.prompt("Command");
            try: self._command(command); self.error=False
            except Exception as exc: self.message(str(exc), True)
        elif key == "?": self.help()
        elif key in ("q", "Q"): self.running=False
        elif isinstance(key,str) and key.isdigit() and key!="0":
            idx=int(key)-1
            if idx < len(self.session.items):
                self.index=idx; self.awaiting_advance=False; self.detail_scroll=0; self.extract_scroll=0
                self.pane_tab = "extraction" if self.path == "processed" else "message"
        elif key == curses.KEY_MOUSE:
            try:
                _id, x, y, _z, bstate = curses.getmouse()
                if x < 48 and 5 <= y < self.screen.getmaxyx()[0]-5:
                    visible_row = y - 5
                    height = self.screen.getmaxyx()[0]-10
                    start=max(0,min(self.index-height+1,max(0,len(self.session.items)-height)))
                    idx=start+visible_row
                    if 0<=idx<len(self.session.items): self.index=idx
            except curses.error: pass
        else:
            self.message(f"Key {key!r} is not assigned. Press ? for help.")

    def run(self) -> None:
        while self.running:
            self.draw()
            if not self._launch_ready_reported:
                # The terminal window has received the first fully rendered
                # frame. Only now can the web app report a successful launch.
                notify_launch_state("ready")
                self._launch_ready_reported = True
                if getattr(self, "auto_extract_pending", False):
                    self.auto_extract_pending = False
                    self.extract()
            try:
                key = self.screen.get_wch()
                if isinstance(key, str) and key == "\x03":
                    self.running=False
                else:
                    self.handle(key)
                self.error = False if not self.error else self.error
            except KeyboardInterrupt:
                self.running=False
            except Exception as exc:
                self.message(str(exc), True)


def main() -> int:
    try:
        curses.wrapper(lambda screen: ReviewDesk(screen).run())
        print("Agent Shadi Review Desk closed. Your data remains in the shared workspace.")
        return 0
    except Exception as exc:
        notify_launch_state("error", f"{type(exc).__name__}: {exc}")
        print(f"Agent Shadi Review Desk: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
