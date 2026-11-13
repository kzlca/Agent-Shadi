#!/usr/bin/env python3
"""Standalone terminal review client for Agent Shadi.

Uses only the Python standard library and the local Agent Shadi HTTP API.
It never opens SQLite directly, so the main application remains the source of truth.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
BASE_URL = os.environ.get("AGENT_SHADI_URL", "http://127.0.0.1:8765").rstrip("/")
DATA = Path(os.environ.get("STRUCTURA_FLOW_DATA", ROOT / "data"))

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
PURPLE = "\033[38;5;141m"
CYAN = "\033[38;5;81m"
GREEN = "\033[38;5;77m"
YELLOW = "\033[38;5;221m"
RED = "\033[38;5;203m"


def color(text: str, shade: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"{shade}{text}{RESET}"


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail")
        except Exception:
            detail = exc.reason
        raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Cannot reach Agent Shadi at {BASE_URL}: {exc}") from exc


def server_is_up() -> bool:
    try:
        api("GET", "/health")
        return True
    except Exception:
        return False


def ensure_server() -> None:
    if server_is_up():
        return
    DATA.mkdir(parents=True, exist_ok=True)
    log_path = DATA / "review-terminal-server.log"
    log = open(log_path, "a", encoding="utf-8")
    command = [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1", "--port", urllib.parse.urlparse(BASE_URL).port.__str__() if urllib.parse.urlparse(BASE_URL).port else "8765"]
    kwargs: dict[str, Any] = {"cwd": str(ROOT), "stdout": log, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)
    log.close()
    for _ in range(80):
        if server_is_up():
            return
        time.sleep(0.25)
    raise RuntimeError(f"Agent Shadi server did not start. Check {log_path}")


def clear_screen() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def shorten(value: Any, width: int = 66) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def parse_rows(spec: str, total: int) -> list[int]:
    selected: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            bits = part.split("-", 1)
            if not all(x.strip().isdigit() for x in bits):
                raise ValueError(f"Invalid row range: {part}")
            start, end = map(lambda x: int(x.strip()), bits)
        else:
            if not part.isdigit():
                raise ValueError(f"Invalid row number: {part}")
            start = end = int(part)
        if start < 1 or end < start or end > total or end - start > 499:
            raise ValueError(f"Choose row numbers between 1 and {total} (maximum 500 at once).")
        selected.update(range(start, end + 1))
    return sorted(selected)


class ReviewTerminal:
    def __init__(self) -> None:
        self.workflows: list[dict[str, Any]] = []
        self.workflow: dict[str, Any] | None = None
        self.path = "processed"
        self.limit = 25
        self.offset = 0
        self.query = ""
        self.source = "all"
        self.items: list[dict[str, Any]] = []
        self.total = 0
        self.has_more = False
        self.selected: set[str] = set()
        self.current_live_record: dict[str, Any] | None = None
        self.undo_token: str | None = None
        self.notice = "Connected to your local Agent Shadi workspace. Type help to begin."
        self.review_settings: dict[str, Any] = {"mode":"guided","processing_path":"processed","auto_advance":True,"confirm_bulk":True,"page_size":100,"sort":"newest"}
        self.review_enabled = True

    @property
    def wid(self) -> str:
        if not self.workflow:
            raise RuntimeError("No workflow is selected")
        return str(self.workflow["id"])

    def load_workflows(self) -> None:
        self.workflows = api("GET", "/api/workflows")
        if not self.workflows:
            raise RuntimeError("No workflows exist yet. Create one in Agent Shadi first.")
        if self.workflow is None:
            self.workflow = self.workflows[0]
        self.load_workflow_settings()

    def load_workflow_settings(self) -> None:
        if not self.workflow:
            return
        detail = api("GET", f"/api/workflows/{self.wid}")
        self.workflow = detail
        config = detail.get("config", {})
        self.review_enabled = config.get("review_mode", True) is not False
        self.review_settings = config.get("review_settings") or self.review_settings
        self.path = self.review_settings.get("processing_path", "processed")

    def save_review_path(self, path: str) -> None:
        body = {
            "enabled": self.review_enabled,
            "mode": self.review_settings.get("mode", "guided"),
            "processing_path": path,
            "auto_advance": self.review_settings.get("auto_advance", True),
            "confirm_bulk": self.review_settings.get("confirm_bulk", True),
            "page_size": self.review_settings.get("page_size", 100),
            "sort": self.review_settings.get("sort", "newest"),
        }
        result = api("PUT", f"/api/workflows/{self.wid}/review/settings", body)
        self.review_settings = result.get("review_settings", body)
        self.review_enabled = result.get("review_mode", self.review_enabled)

    def load_queue(self) -> None:
        if self.path == "live":
            params = {"limit": self.limit, "offset": self.offset, "q": self.query, "source": self.source}
            data = api("GET", f"/api/workflows/{self.wid}/review/live/queue?{urllib.parse.urlencode(params)}")
        else:
            params = {"limit": self.limit, "offset": self.offset, "q": self.query, "source": self.source}
            data = api("GET", f"/api/workflows/{self.wid}/review/queue?{urllib.parse.urlencode(params)}")
        self.items = data.get("items", [])
        self.total = int(data.get("total", 0))
        self.has_more = bool(data.get("has_more", False))

    def render(self) -> None:
        clear_screen()
        cols = max(72, shutil.get_terminal_size((100, 30)).columns)
        line = "─" * min(cols, 100)
        title = "AGENT SHADI  /  REVIEW TERMINAL"
        print(color(title, PURPLE + BOLD))
        print(color(line, DIM))
        wf_name = self.workflow.get("name", "Unknown") if self.workflow else "No workflow"
        mode = "LIVE AI · one message per call" if self.path == "live" else "PROCESSED · review existing AI results"
        print(f"{color('WORKFLOW', CYAN)}  {wf_name}")
        print(f"{color('PATH', CYAN)}      {mode}")
        print(f"{color('QUEUE', CYAN)}     {len(self.items)} shown / {self.total} total · page offset {self.offset}")
        print(color(line, DIM))
        if self.path == "live":
            print(color(" #   STATE       SOURCE / MESSAGE", BOLD))
            for i, item in enumerate(self.items, 1):
                status = str(item.get("status", "queued")).upper()
                shade = RED if status == "FAILED" else YELLOW if status == "INTERRUPTED" else CYAN
                source = shorten(item.get("source") or "Unknown source", 18)
                message = shorten(item.get("raw_text"), max(20, min(cols - 40, 65)))
                print(f"{color(f'{i:>2}', PURPLE)}  {color(f"{status:<11}", shade)} {source:<18} {message}")
        else:
            print(color(" #   CONF.  STATE        SOURCE / EXTRACTED PREVIEW", BOLD))
            for i, item in enumerate(self.items, 1):
                status = str(item.get("status", "needs_review")).upper()
                conf = f"{float(item.get('confidence') or 0)*100:4.0f}%"
                source = shorten(item.get("source") or "Unknown source", 15)
                preview = " · ".join(str(v) for v in (item.get("data") or {}).values() if v not in (None, ""))
                shade = RED if item.get("errors") else YELLOW if item.get("warnings") else GREEN
                print(f"{color(f'{i:>2}', PURPLE)}  {conf}  {color(f"{status:<11}", shade)} {source:<15} {shorten(preview, max(20, min(cols - 54, 70)))}")
        if self.current_live_record:
            print(color(line, DIM))
            print(color("CURRENT LIVE AI RESULT — DECISION REQUIRED", YELLOW + BOLD))
            print(json.dumps(self.current_live_record.get("data", {}), ensure_ascii=False, indent=2))
        if self.selected:
            print(color(f"Selected IDs: {len(self.selected)}", YELLOW))
        print(color(line, DIM))
        print(self.notice)
        print(color("Type help · ?  |  q to quit", DIM))

    def row(self, number: int) -> dict[str, Any]:
        if number < 1 or number > len(self.items):
            raise ValueError(f"Choose a visible row between 1 and {len(self.items)}")
        return self.items[number - 1]

    def show_row(self, number: int) -> None:
        item = self.row(number)
        clear_screen()
        print(color(f"RECORD {number} / {len(self.items)}", PURPLE + BOLD))
        print(color("─" * 72, DIM))
        if self.path == "live":
            print(f"Source: {item.get('source')}  |  Date: {item.get('posted_at')}  |  State: {item.get('status')}")
            print("\nORIGINAL MESSAGE\n")
            print(item.get("raw_text", ""))
            if item.get("error"):
                print(color(f"\nPrevious error: {item['error']}", RED))
            print(color("\nRun: extract " + str(number), CYAN))
        else:
            print(f"Source: {item.get('source')}  |  Date: {item.get('posted_at')}  |  Confidence: {float(item.get('confidence') or 0)*100:.0f}%")
            print("\nORIGINAL MESSAGE\n")
            print(item.get("raw_text", ""))
            print("\nEXTRACTED DATA\n")
            print(json.dumps(item.get("data", {}), ensure_ascii=False, indent=2))
            if item.get("errors"):
                print(color("\nERRORS\n" + "\n".join(map(str, item["errors"])), RED))
            if item.get("warnings"):
                print(color("\nWARNINGS\n" + "\n".join(map(str, item["warnings"])), YELLOW))
        input("\nPress Enter to return…")

    def decide(self, action: str, ids: list[str]) -> None:
        ids = list(dict.fromkeys(ids))
        if not ids:
            raise ValueError("No records selected")
        if action == "reject" and input(f"Reject {len(ids)} record(s)? Type y to confirm: ").strip().lower() != "y":
            self.notice = "Rejection cancelled."
            return
        if len(ids) == 1:
            result = api("POST", f"/api/records/{ids[0]}/{action}", {"reason": "Standalone review terminal"} if action == "reject" else None)
        else:
            result = api("POST", f"/api/workflows/{self.wid}/records/bulk-action", {"ids": ids, "action": action, "reason": "Standalone review terminal batch"})
        self.undo_token = result.get("undo_token") or self.undo_token
        self.current_live_record = None
        self.selected.difference_update(ids)
        self.notice = f"{result.get('updated', 1 if len(ids)==1 else len(ids))} record(s) {action}d. Type undo to restore the last decision."
        self.load_queue()

    def run(self, command: str) -> bool:
        bits = command.strip().split(maxsplit=1)
        if not bits:
            return True
        op = bits[0].lower()
        arg = bits[1].strip() if len(bits) > 1 else ""
        if op in {"q", "quit", "exit"}:
            return False
        if op in {"help", "?"}:
            self.notice = (
                "Commands: list | show N | path processed|live | workflows | workflow N | next | prev | page N | "
                "extract N | approve N | reject N | approve current | reject current | "
                "select 1-5 | approve selected | reject selected | edit N | undo | search TEXT | clear | quit"
            )
        elif op == "path":
            if arg not in {"processed", "live"}:
                raise ValueError("Use path processed or path live")
            if self.current_live_record and arg != "live":
                raise ValueError("Approve/reject the current live result before switching paths")
            self.save_review_path(arg)
            self.path = arg; self.offset = 0; self.selected.clear(); self.current_live_record = None; self.notice = f"Review path saved: {arg}"
            self.load_queue()
        elif op == "workflow":
            if not arg.isdigit() or not 1 <= int(arg) <= len(self.workflows):
                listing = ", ".join(f"{i+1}:{w['name']}" for i,w in enumerate(self.workflows))
                raise ValueError(f"Use workflow N. Available: {listing}")
            self.workflow = self.workflows[int(arg)-1]; self.offset = 0; self.selected.clear(); self.current_live_record = None; self.load_workflow_settings(); self.load_queue(); self.notice = f"Workflow changed to {self.workflow['name']} · path {self.path}"
        elif op in {"workflows", "wf"}:
            self.notice = "Workflows: " + " | ".join(f"{i+1}: {w['name']}" for i,w in enumerate(self.workflows)) + " · switch with workflow N"
        elif op in {"list", "refresh", "ls"}:
            self.load_queue(); self.notice = "Queue refreshed."
        elif op in {"page", "offset"}:
            if not arg.isdigit(): raise ValueError("Use page N")
            self.offset = max(0, (int(arg)-1)*self.limit); self.load_queue(); self.notice = f"Opened page {int(arg)}"
        elif op == "next":
            if self.current_live_record: raise ValueError("Approve/reject the current live result before moving on")
            if self.items and len(self.items) < self.total - self.offset:
                self.offset += self.limit; self.load_queue()
            else:
                self.notice = "No next queue page."
        elif op in {"prev", "previous"}:
            self.offset = max(0, self.offset-self.limit); self.load_queue(); self.notice = "Previous page loaded."
        elif op == "search":
            self.query = arg; self.offset = 0; self.load_queue(); self.notice = f"Search: {arg or '(cleared)'}"
        elif op == "clear":
            self.query = ""; self.source = "all"; self.offset = 0; self.selected.clear(); self.load_queue(); self.notice = "Search and selection cleared."
        elif op in {"show", "open"}:
            if not arg.isdigit(): raise ValueError("Use show N")
            self.show_row(int(arg)); self.notice = "Returned from record detail."
        elif op == "extract":
            if self.path != "live": raise ValueError("Use path live before extracting a raw message")
            if self.current_live_record: raise ValueError("A live AI result is already awaiting your decision")
            if not arg.isdigit(): raise ValueError("Use extract N")
            item = self.row(int(arg))
            result = api("POST", f"/api/workflows/{self.wid}/review/live/{item['id']}/extract")
            self.current_live_record = result["record"]
            self.notice = f"AI extracted {len(self.current_live_record.get('data', {}))} fields. Review then use approve current or reject current."
            self.load_queue()
        elif op in {"approve", "reject"} and arg.lower() == "current":
            if self.path != "live" or not self.current_live_record:
                raise ValueError("There is no live extraction awaiting a decision")
            rid = self.current_live_record["id"]
            result = api("POST", f"/api/records/{rid}/{op}", {"reason": "Standalone live review terminal"} if op == "reject" else None)
            self.undo_token = result.get("undo_token") or self.undo_token
            self.current_live_record = None
            self.load_queue()
            self.notice = f"Current live result {op}d."
        elif op in {"approve", "reject"}:
            if self.path == "live": raise ValueError("In live mode, extract one message, then use approve current or reject current")
            ids = list(self.selected) if arg.lower() == "selected" else [self.row(n)["id"] for n in parse_rows(arg, len(self.items))]
            self.decide(op, ids)
        elif op == "select":
            if self.path == "live": raise ValueError("Live AI review processes one raw message at a time")
            if arg.lower() == "all": ids = [x["id"] for x in self.items]
            else: ids = [self.row(n)["id"] for n in parse_rows(arg, len(self.items))]
            self.selected.update(ids); self.notice = f"{len(ids)} record(s) selected."
        elif op == "edit":
            if self.path == "live" and not self.current_live_record: raise ValueError("Extract a message first, then use edit current in the web Review Studio")
            if self.path == "live": raise ValueError("Use the web editor for the current live result in this release")
            if not arg.isdigit(): raise ValueError("Use edit N")
            item = self.row(int(arg)); print(json.dumps(item.get("data", {}), ensure_ascii=False, indent=2))
            raw = input("Paste complete JSON object with corrected fields: ").strip()
            updated = json.loads(raw)
            if not isinstance(updated, dict): raise ValueError("Edited value must be a JSON object")
            api("PUT", f"/api/records/{item['id']}", {"data": updated}); self.load_queue(); self.notice = "Record corrections saved."
        elif op == "undo":
            if not self.undo_token: raise ValueError("No decision to undo in this terminal session")
            result = api("POST", f"/api/workflows/{self.wid}/quality/undo", {"undo_token": self.undo_token})
            self.undo_token = None; self.load_queue(); self.notice = f"Undo restored {result.get('restored', 0)} action(s)."
        else:
            raise ValueError("Unknown command. Type help.")
        return True

    def main(self) -> int:
        ensure_server()
        self.load_workflows()
        self.load_queue()
        while True:
            self.render()
            try:
                command = input(color("shadi-review › ", PURPLE + BOLD)).strip()
                if not self.run(command):
                    break
            except KeyboardInterrupt:
                print("\nUse q to quit cleanly.")
            except Exception as exc:
                self.notice = color(str(exc), RED)
        print(color("Agent Shadi Review Terminal closed. Your records remain saved.", GREEN))
        return 0


def main() -> int:
    try:
        return ReviewTerminal().main()
    except Exception as exc:
        print(color(f"Agent Shadi Review Terminal: {exc}", RED), file=sys.stderr)
        print(f"Server log: {DATA / 'review-terminal-server.log'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # Keep this historical entry point useful: direct execution opens the
    # keyboard-first full-screen Review Desk rather than the old line prompt.
    from review_tui import main as review_desk_main
    raise SystemExit(review_desk_main())
